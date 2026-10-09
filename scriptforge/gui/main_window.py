"""Main window and process entry point.

Threading contract, and it is the load-bearing part of this file:

  pexpect's forkpty() must be reached from the process' main thread. Qt delivers
  queued signal slots on the thread that owns the receiver, so RunWorker lives
  on a QThread and MainWindow.pre_run() (main thread) performs the fork via
  ScriptRunner.prepare() before the worker starts. Nothing else touches
  run_interactive() on the GUI path.

Qt needs no TTY, which is what fixes the reported symptom: launching from a
.desktop file or a Start-menu shortcut gives the child a console-less,
no-stdin environment, and a wrapper that assumed a terminal died there.
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from .. import __version__
from ..core.parser.classify import analyze, scan_directory
from ..core.runner import RunResult, ScriptRunner
from ..forge import forge
from . import strings as S
from .panels import HistoryPanel, InterfacePanel, OverviewPanel, RunPanel, ScriptList
from .style import stylesheet

DEFAULT_ROOTS = [
    Path.home() / "bin",
    Path.home() / ".local" / "bin",
    Path("/usr/local/bin"),
    Path("/usr/bin"),
]

ICON_CANDIDATES = [
    Path(__file__).resolve().parents[1] / "assets" / "scriptforge.png",
    Path("/usr/share/icons/hicolor/256x256/apps/scriptforge.png"),
    Path("/usr/share/icons/hicolor/scalable/apps/scriptforge.svg"),
]

KIND_ORDER = {"interactive": 0, "parametric": 1, "skeletal": 2, "fullscreen": 3, "opaque": 4}


class RunWorker(QtCore.QObject):
    """Drives one run. Lives on a worker thread; emits only Qt signals."""

    chunk = QtCore.Signal(str)
    done = QtCore.Signal(object)

    def __init__(self, script: Path, answers: dict[str, str], timeout: int):
        super().__init__()
        self.script = script
        self.answers = answers
        self.timeout = timeout

    @QtCore.Slot()
    def execute(self) -> None:
        # Answers and timeout belong to the runner, not to run_interactive();
        # pass them at construction or the queue is empty and the child hangs
        # on its first read.
        runner = ScriptRunner(self.script, answers=self.answers, timeout=self.timeout)
        try:
            result = runner.run_interactive(on_output=self.chunk.emit)
        except Exception as exc:  # a dead child must surface, not vanish
            result = RunResult(
                argv=[str(self.script)],
                exit_code=255,
                output=f"{type(exc).__name__}: {exc}\n",
                duration_s=0.0,
            )
        self.done.emit(result)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, roots: list[Path] | None = None, lang: str = "en"):
        super().__init__()
        self.s = S.CATALOG.get(lang, S.EN)
        # An explicit root that does not exist stays on the list: silently
        # replacing it with ~/bin turns "you pointed at the wrong path" into
        # "here are 25 unrelated scripts", which reads as a working app.
        self.roots = [Path(r).expanduser() for r in (roots if roots is not None else DEFAULT_ROOTS)]
        if not self.roots:
            self.roots = [Path.home() / "bin"]
        self.current = None
        self._thread: QtCore.QThread | None = None
        self._worker: RunWorker | None = None

        self.setWindowTitle(f"ScriptForge {__version__}")
        self.resize(1180, 720)
        self.setMinimumSize(880, 560)

        self._build()
        self.apply_language(self.s)
        self._load_icon()
        self.rescan()

        QtCore.QTimer.singleShot(0, self._autoselect_first)

    # --- construction ------------------------------------------------------
    def _build(self) -> None:
        self.sidebar = ScriptList(self.s)
        self.sidebar.setMinimumWidth(250)
        self.sidebar.selected.connect(self.on_select)
        self.sidebar.activate.connect(self.on_run)

        self.overview = OverviewPanel(self.s)
        self.interface = InterfacePanel(self.s)
        self.run_panel = RunPanel(self.s)
        self.history = HistoryPanel(self.s)
        self.run_panel.finished.connect(self._on_run_finished)

        self.tabs = QtWidgets.QTabWidget()
        for panel in (self.overview, self.interface, self.run_panel, self.history):
            self.tabs.addTab(panel, "")

        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        split.addWidget(self.sidebar)
        split.addWidget(self.tabs)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([290, 890])
        self.setCentralWidget(split)

        self.toolbar = QtWidgets.QToolBar("main")
        self.toolbar.setMovable(False)
        self.act_rescan = self._action("⟳", lambda: self.rescan())
        self.act_forge = self._action("✦", self.on_forge)
        self.act_run = self._action("▶", self.on_run)
        self.act_run.setObjectName("primary")
        self.act_stop = self._action("■", self.on_stop)
        self.act_stop.setObjectName("danger")
        self.act_clear = self._action("⌫", lambda: self.run_panel.clear())
        self.act_lang = self._action("", self.toggle_language)
        self.act_lang.setObjectName("lang")
        for act in (self.act_rescan, self.act_forge, self.act_run, self.act_stop, self.act_clear):
            self.toolbar.addAction(act)
        self.toolbar.addSeparator()
        spacer = QtWidgets.QWidget()
        spacer.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        self.toolbar.addWidget(spacer)
        self.toolbar.addAction(self.act_lang)
        self.addToolBar(self.toolbar)

        self.roots_label = QtWidgets.QLabel("")
        self.roots_label.setObjectName("faint")
        self.statusBar().addPermanentWidget(self.roots_label)
        self.statusBar().showMessage(self.s.ready)

    def _action(self, text: str, slot) -> QtGui.QAction:
        act = QtGui.QAction(text, self)
        act.triggered.connect(slot)
        return act

    def _load_icon(self) -> None:
        for candidate in ICON_CANDIDATES:
            if candidate.exists():
                self.setWindowIcon(QtGui.QIcon(str(candidate)))
                return

    def _autoselect_first(self) -> None:
        if self.current is None and self.sidebar.list.count():
            self.sidebar.list.setCurrentRow(0)

    # --- data --------------------------------------------------------------
    def rescan(self) -> None:
        """Re-read every root.

        A root that is unreadable or missing is skipped rather than raising: the
        common case is a Kali box where ~/bin does not exist yet, and that must
        not look like a failure.
        """

        found: list = []
        seen: set[Path] = set()
        for root in self.roots:
            try:
                scripts = scan_directory(root)
            except Exception:
                continue
            for script in scripts:
                try:
                    resolved = script.path.resolve()
                except OSError:
                    continue
                if resolved in seen:
                    continue
                seen.add(resolved)
                found.append(script)
        found.sort(key=lambda i: (KIND_ORDER.get(i.kind.value, 9), i.path.name.lower()))
        self.sidebar.set_scripts(found)
        self.history.reload()
        self.roots_label.setText(
            f"{len(self.roots)} {self.s.field_path.lower()} · {len(found)} {self.s.scripts_found}"
        )
        self.statusBar().showMessage(self.s.ready, 3000)

    def on_select(self, script) -> None:
        self.current = script
        self.overview.set_script(script)
        self.interface.set_script(script)
        self.act_run.setEnabled(script is not None)
        self.act_forge.setEnabled(script is not None)

    # --- forge -------------------------------------------------------------
    def on_forge(self) -> None:
        if self.current is None:
            return
        try:
            result = forge(self.current.path, force=True)
        except Exception as exc:
            self.statusBar().showMessage(f"{self.s.forge_failed}: {exc}", 8000)
            return
        if result.ok:
            self.statusBar().showMessage(f"{self.s.forged}: {result.generated}", 8000)
            # The wrapper is now a script in its own right; make it selectable.
            try:
                self.roots.append(result.generated.parent)
            except Exception:
                pass
            self.rescan()
        else:
            self.statusBar().showMessage(f"{self.s.forge_failed}: {result.message}", 8000)

    # --- run ---------------------------------------------------------------
    def on_run(self) -> None:
        if self.current is None or self._thread is not None:
            return
        answers = dict(self.interface.answers())
        answers.update(self._parse_console_answers())

        script = self.current.path
        try:
            # Main-thread fork. See the module docstring: this is what keeps the
            # child from deadlocking under Qt's thread pool.
            ScriptRunner(script, answers=answers).prepare()
        except Exception as exc:
            self.statusBar().showMessage(f"fork failed: {exc}", 8000)
            return

        self.tabs.setCurrentWidget(self.run_panel)
        self.run_panel.set_busy(True)
        self.act_run.setEnabled(False)
        self.act_stop.setEnabled(True)

        self._thread = QtCore.QThread(self)
        self._worker = RunWorker(script, answers, timeout=300)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.execute)
        self._worker.chunk.connect(self.run_panel.append)
        self._worker.done.connect(self._run_done)
        self._thread.start()

    def _run_done(self, result: RunResult) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(5000)
            self._thread = None
        self._worker = None
        self.act_run.setEnabled(self.current is not None)
        self.act_stop.setEnabled(False)
        self.run_panel.set_busy(False)
        self.run_panel.set_result(result)

    def on_stop(self) -> None:
        # Killing the thread would abort mid-write on the pty. Waiting for the
        # child to exit keeps the vault row and console consistent.
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(3000)
        self._thread = None
        self._worker = None
        self.act_run.setEnabled(self.current is not None)
        self.act_stop.setEnabled(False)
        self.run_panel.set_busy(False)

    def _on_run_finished(self, result: RunResult) -> None:
        self.history.reload()

    def _parse_console_answers(self) -> dict[str, str]:
        raw = self.run_panel.answers_edit.toPlainText()
        out: dict[str, str] = {}
        for line in raw.splitlines():
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            key, value = key.strip(), value.strip()
            if key and value:
                out[key] = value
        return out

    # --- language ----------------------------------------------------------
    def toggle_language(self) -> None:
        target = "ar" if self.s.lang == "en" else "en"
        self.apply_language(S.CATALOG[target])

    def apply_language(self, s: S.Strings) -> None:
        self.s = s
        self.setWindowTitle(f"ScriptForge {__version__}")
        self.setLayoutDirection(QtCore.Qt.RightToLeft if s.rtl else QtCore.Qt.LeftToRight)

        for index, title in enumerate(
            (s.tabs_overview, s.tabs_interface, s.tabs_run, s.tabs_history)
        ):
            self.tabs.setTabText(index, title)

        glyphs = {
            "rescan": "⟳",
            "forge": "✦",
            "run": "▶",
            "stop": "■",
            "clear": "⌫",
        }
        self.act_rescan.setText(f"{glyphs['rescan']}  {s.rescan}")
        self.act_forge.setText(f"{glyphs['forge']}  {s.forge}")
        self.act_run.setText(f"{glyphs['run']}  {s.run}")
        self.act_stop.setText(f"{glyphs['stop']}  {s.stop}")
        self.act_clear.setText(f"{glyphs['clear']}  {s.clear}")
        self.act_lang.setText(s.language)

        self.act_run.setToolTip(s.run)
        self.act_forge.setToolTip(s.forge)
        self.act_stop.setToolTip(s.stop)

        self.sidebar.set_strings(s)
        self.overview.set_strings(s)
        self.interface.set_strings(s)
        self.run_panel.set_strings(s)
        self.history.set_strings(s)
        self.statusBar().showMessage(self.s.ready, 2500)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(2000)
        super().closeEvent(event)


def _no_display() -> str | None:
    """Return why a window cannot be opened, or None if one can.

    Checked before QApplication is constructed because Qt's own failure mode
    here is abort(), not an exception.
    """

    if sys.platform not in ("linux", "linux2"):
        return None
    if os.environ.get("QT_QPA_PLATFORM"):
        return None
    if os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"):
        return None
    if os.environ.get("XDG_SESSION_TYPE") == "wayland":
        return None
    return "neither DISPLAY nor WAYLAND_DISPLAY is set"


def run(argv: list[str] | None = None) -> int:
    """Qt entry point.

    Exit codes follow the shell convention so wrapper scripts can branch on
    them: 0 clean, 1 argument error, 2 the Qt platform plugin failed to load,
    3 an unexpected exception escaped a slot.
    """

    parser = argparse.ArgumentParser(
        prog="scriptforge-gui",
        description="ScriptForge desktop interface",
    )
    parser.add_argument("roots", nargs="*", help="folders to scan (default: ~/bin, /usr/local/bin)")
    parser.add_argument("--lang", default="en", choices=["en", "ar"])
    args = parser.parse_args(argv)

    problem = _no_display()
    if problem:
        # Qt aborts the process with SIGABRT here, which a .desktop user sees as
        # the app "closing itself" with no message. Fail loudly instead.
        print(f"  Cannot open a window: {problem}", file=sys.stderr)
        print(
            "  This usually means the app was started outside a graphical "
            "session.\n"
            "  Run it from your desktop session, or set QT_QPA_PLATFORM=offscreen "
            "for a headless check.",
            file=sys.stderr,
        )
        return 2

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])
    app.setApplicationName("ScriptForge")
    app.setApplicationDisplayName("ScriptForge")
    app.setOrganizationName("AIHAM AM")
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    app.setStyleSheet(stylesheet())

    window = MainWindow(roots=[Path(r) for r in args.roots] or None, lang=args.lang)
    window.show()

    # A traceback inside a slot is otherwise swallowed by Qt and the window just
    # stops responding, which reads as the exact "it crashed" symptom we are
    # fixing. Surface it on stderr and keep the window alive.
    def _hook(kind, value, tb) -> None:
        if issubclass(kind, KeyboardInterrupt):
            sys.__excepthook__(kind, value, tb)
            return
        traceback.print_exception(kind, value, tb, file=sys.stderr)

    sys.excepthook = _hook
    return app.exec()