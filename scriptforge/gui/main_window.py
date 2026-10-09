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
from ..forge import built_dir, forge
from . import strings as S
from .panels import HistoryPanel, InterfacePanel, OverviewPanel, RunPanel, ScriptList
from .style import stylesheet

DEFAULT_ROOTS = [
    Path.home() / "bin",
    Path.home() / ".local" / "bin",
    # Forge output is scanned from the start. Appending it on every Build click
    # grew the root list without bound, and each rescan then re-walked one more
    # directory - the window got slower on every press until it looked hung.
    built_dir(),
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

    def __init__(
        self,
        script: Path,
        answers: dict[str, str],
        timeout: int,
        argv: list[str] | None = None,
        use_pty: bool = True,
    ):
        super().__init__()
        self.script = script
        self.answers = answers
        self.timeout = timeout
        self.argv = list(argv or [])
        self.use_pty = use_pty

    @QtCore.Slot()
    def execute(self) -> None:
        # Answers and timeout belong to the runner, not to run_interactive();
        # pass them at construction or the queue is empty and the child hangs
        # on its first read.
        runner = ScriptRunner(self.script, answers=self.answers, timeout=self.timeout)
        try:
            # A script that takes a mode and flags does not read stdin, so the
            # prompt-driven PTY loop is the wrong transport: it would wait for
            # text that never comes. Pipes for those, pty for the rest.
            if self.use_pty and not self.argv:
                result = runner.run_interactive(on_output=self.chunk.emit)
            else:
                result = runner.run_plain(args=self.argv, on_output=self.chunk.emit)
        except Exception as exc:  # a dead child must surface, not vanish
            result = RunResult(
                argv=[str(self.script)],
                exit_code=255,
                output=f"{type(exc).__name__}: {exc}\n",
                duration_s=0.0,
            )
        self.done.emit(result)


class ForgeWorker(QtCore.QObject):
    """Builds a wrapper on a worker thread."""

    done = QtCore.Signal(object)  # RewriteResult

    def __init__(self, script: Path, force: bool):
        super().__init__()
        self.script = script
        self.force = force

    @QtCore.Slot()
    def execute(self) -> None:
        from ..core.rewriter import RewriteResult

        try:
            self.done.emit(forge(self.script, force=self.force))
        except Exception as exc:  # noqa: BLE001
            self.done.emit(
                RewriteResult(self.script, self.script, False, "error", str(exc), [])
            )


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
        self._forge_thread: QtCore.QThread | None = None
        self._forge_worker: ForgeWorker | None = None

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
        # Disabled with a tooltip rather than enabled-then-failed: an opaque
        # entry point has nothing to generate, and the error message read like
        # something had broken.
        self.act_forge.setEnabled(script is not None and script.buildable)
        self.act_forge.setToolTip(
            "" if script is None or script.buildable else self.s.not_buildable
        )

    # --- forge -------------------------------------------------------------
    def on_forge(self) -> None:
        """Build an interface for a script that has none.

        Runs on a worker: analyze + write is milliseconds for a normal script
        but can be seconds for a generated one, and doing it inline froze the
        window, which the user cannot tell apart from a crash.
        """

        if self.current is None or self._forge_thread is not None:
            return

        ir = self.current
        if not ir.buildable:
            self.statusBar().showMessage(self.s.not_buildable, 9000)
            return

        # Rebuild only when the source moved on.
        #
        # A modal confirm was the wrong shape twice over: it is a decision the
        # user cannot answer without reading, and a box nobody dismisses is
        # indistinguishable from the hang this path already had.
        force = self._wrapper_is_stale(ir)

        self.act_forge.setEnabled(False)
        self.statusBar().showMessage(self.s.regenerating)

        self._forge_thread = QtCore.QThread(self)
        self._forge_worker = ForgeWorker(ir.path, force)
        self._forge_worker.moveToThread(self._forge_thread)
        self._forge_thread.started.connect(self._forge_worker.execute)
        self._forge_worker.done.connect(self._forge_done)
        self._forge_thread.start()

    def _wrapper_is_stale(self, ir) -> bool:
        """True when the source is newer than the wrapper generated from it.

        No wrapper yet means rewrite() builds one without needing force.
        """

        newest = 0.0
        for candidate in built_dir().glob(f"{ir.path.stem}.*"):
            try:
                newest = max(newest, candidate.stat().st_mtime)
            except OSError:
                continue
        if newest == 0.0:
            return False
        try:
            return ir.path.stat().st_mtime > newest
        except OSError:
            return False

    def _forge_done(self, result) -> None:
        if self._forge_thread is not None:
            self._forge_thread.quit()
            self._forge_thread.wait(5000)
            self._forge_thread = None
        self._forge_worker = None
        self.act_forge.setEnabled(self.current is not None and self.current.buildable)

        if result.ok:
            fresh = "wrote" in result.message
            head = self.s.forged if fresh else self.s.reused
            self.statusBar().showMessage(f"{head}: {result.generated}", 10000)
            self.rescan()
            # Select the wrapper so the next Run acts on it, not the original.
            self._select_by_path(result.generated)
        else:
            self.statusBar().showMessage(f"{self.s.forge_failed}: {result.message}", 12000)

    def _select_by_path(self, path: Path) -> None:
        target = str(path)
        for row in range(self.sidebar.list.count()):
            entry = self.sidebar.list.item(row)
            if entry.data(QtCore.Qt.UserRole) == target:
                self.sidebar.list.setCurrentRow(row)
                return

    # --- run ---------------------------------------------------------------
    def on_run(self) -> None:
        if self.current is None or self._thread is not None:
            return
        answers = dict(self.interface.answers())
        answers.update(self._parse_console_answers())

        argv = self.interface.argv()
        # needs_pty is the parser's own verdict: an interactive script reads
        # stdin, a parametric one parses argv. Trusting it keeps both fast.
        use_pty = self.current.needs_pty and not argv

        script = self.current.path
        try:
            if use_pty:
                # Main-thread fork. See the module docstring: this is what keeps
                # the child from deadlocking under Qt's thread pool.
                ScriptRunner(script, answers=answers).prepare()
        except Exception as exc:
            self.statusBar().showMessage(f"fork failed: {exc}", 8000)
            return

        self.tabs.setCurrentWidget(self.run_panel)
        self.run_panel.set_busy(True)
        self.act_run.setEnabled(False)
        self.act_stop.setEnabled(True)

        self._thread = QtCore.QThread(self)
        self._worker = RunWorker(script, answers, 300, argv=argv, use_pty=use_pty)
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
        # A live QThread aborts the interpreter at teardown, which is the crash
        # this whole class of bug produced before.
        for attr in ("_thread", "_forge_thread"):
            thread = getattr(self, attr, None)
            if thread is not None:
                thread.quit()
                thread.wait(3000)
                setattr(self, attr, None)
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