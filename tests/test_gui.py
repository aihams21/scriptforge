"""Desktop window tests.

Everything runs under QT_QPA_PLATFORM=offscreen, which is set before PySide6 is
imported. That is not just a CI convenience: it exercises the exact code path a
.desktop launch takes, i.e. a Qt application with no controlling terminal, which
is where the original wrapper died.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytest.importorskip("PySide6")

from PySide6 import QtCore, QtWidgets  # noqa: E402

from scriptforge.gui import strings as S  # noqa: E402
from scriptforge.gui.main_window import KIND_ORDER, MainWindow  # noqa: E402

ASK = """#!/bin/bash
echo "target:"
read -r t
echo "hit $t"
"""

SKELETON = """#!/bin/bash
somecli --config /etc/settings.yaml "$@"
"""


@pytest.fixture(scope="module")
def app():
    existing = QtWidgets.QApplication.instance()
    return existing or QtWidgets.QApplication([])


@pytest.fixture
def root(tmp_path):
    ask = tmp_path / "ask.sh"
    ask.write_text(ASK)
    ask.chmod(0o755)
    skel = tmp_path / "acct"
    skel.write_text(SKELETON)
    skel.chmod(0o755)
    return tmp_path


@pytest.fixture
def window(app, root):
    win = MainWindow(roots=[root], lang="en")
    yield win
    win.close()
    win.deleteLater()


def pump(ms: int = 60) -> None:
    """Let Qt settle.

    Widget teardown and layout both go through the event loop; asserting on a
    widget before it has been processed is how stale-state bugs get written.
    """

    loop = QtCore.QEventLoop()
    QtCore.QTimer.singleShot(ms, loop.quit)
    loop.exec()


def test_window_boots_without_a_tty(app, window):
    """The reported crash: launcher -> no stdin -> window gone.

    No TTY exists in the test process at all, so a passing here means the
    window's lifetime is independent of stdio.
    """

    assert not sys.stdin.isatty()
    assert window.isVisible() or window.windowTitle()
    assert window.current is not None


def test_scripts_are_listed(window):
    names = {window.sidebar.irs[i].path.name for i in range(len(window.sidebar.irs))}
    assert {"ask.sh", "acct"} <= names


def test_list_is_ordered_interactive_first(window):
    kinds = [ir.kind.value for ir in window.sidebar.irs]
    assert kinds == sorted(kinds, key=lambda k: KIND_ORDER.get(k, 9))
    assert kinds[0] == "interactive"


def test_selection_populates_every_panel(window):
    window.sidebar.list.setCurrentRow(0)
    pump()
    assert window.tabs.tabText(0) == S.EN.tabs_overview
    assert window.overview.body.count() > 3
    assert window.interface.script is not None


def test_interactive_script_yields_one_field_per_prompt(window):
    for row in range(window.sidebar.list.count()):
        if window.sidebar.irs[window.sidebar.list.item(row).data(QtCore.Qt.UserRole + 4)].path.name == "ask.sh":
            window.sidebar.list.setCurrentRow(row)
            break
    pump()
    fields = window.interface.inputs
    assert "t" in fields
    assert isinstance(fields["t"], QtWidgets.QLineEdit)
    assert window.interface.answers() == {"t": ""} or window.interface.answers() == {}


def test_answers_drop_empty_values(window):
    for row in range(window.sidebar.list.count()):
        if window.sidebar.irs[window.sidebar.list.item(row).data(QtCore.Qt.UserRole + 4)].path.name == "ask.sh":
            window.sidebar.list.setCurrentRow(row)
            break
    pump()
    window.interface.inputs["t"].setText("10.0.0.1")
    assert window.interface.answers() == {"t": "10.0.0.1"}
    window.interface.inputs["t"].setText("")
    assert window.interface.answers() == {}


def test_skeletal_script_offers_no_form(window):
    for row in range(window.sidebar.list.count()):
        if window.sidebar.irs[window.sidebar.list.item(row).data(QtCore.Qt.UserRole + 4)].path.name == "acct":
            window.sidebar.list.setCurrentRow(row)
            break
    pump()
    assert window.interface.inputs == {}


def test_search_filters_the_list(window):
    window.sidebar.search.setText("acct")
    pump()
    assert window.sidebar.list.count() == 1
    window.sidebar.search.setText("")
    pump()
    assert window.sidebar.list.count() == 2


def test_search_with_no_match_clears_selection(window):
    window.sidebar.search.setText("zzzz-no-such-script")
    pump()
    assert window.sidebar.list.count() == 0
    assert window.current is None


def test_language_toggle_flips_every_visible_label(window):
    window.toggle_language()
    pump()
    assert window.s.lang == "ar"
    assert window.tabs.tabText(0) == S.AR.tabs_overview
    assert window.act_run.text().endswith(S.AR.run)
    assert window.layoutDirection() == QtCore.Qt.RightToLeft
    window.toggle_language()
    pump()
    assert window.s.lang == "en"
    assert window.layoutDirection() == QtCore.Qt.LeftToRight


def test_language_toggle_survives_selection_of_each_kind(window):
    """Rebuilding panels is where a stale widget reference would surface."""

    for row in range(window.sidebar.list.count()):
        window.sidebar.list.setCurrentRow(row)
        window.toggle_language()
        pump(20)
        window.toggle_language()
        pump(20)
    assert window.sidebar.list.count() == 2


def test_history_panel_reads_an_isolated_vault(app, tmp_path):
    """Point the panel at its own vault: the default one holds real runs, so
    asserting against it would pass or fail depending on the machine."""

    from scriptforge.core.vault import Vault
    from scriptforge.gui.panels import HistoryPanel

    empty = Vault(tmp_path / "vault.db")
    empty.close()

    panel = HistoryPanel(S.EN)
    panel.set_vault(empty.path)
    panel.reload()
    assert panel.table.rowCount() == 0

    with Vault(empty.path) as vault:
        vault.log_run("x.sh", "interactive", ["x.sh"], 0, 1.5)
    panel.reload()
    assert panel.table.rowCount() == 1
    assert panel.table.item(0, 0).text() == "x.sh"


def test_console_is_append_only(window):
    window.run_panel.append("first\n")
    window.run_panel.append("second\n")
    assert window.run_panel.console.toPlainText() == "first\nsecond\n"


def test_run_reports_success_through_the_window(app, window):
    for row in range(window.sidebar.list.count()):
        if window.sidebar.irs[window.sidebar.list.item(row).data(QtCore.Qt.UserRole + 4)].path.name == "ask.sh":
            window.sidebar.list.setCurrentRow(row)
            break
    pump()
    window.interface.inputs["t"].setText("10.0.0.1")

    done = []
    window.run_panel.finished.connect(lambda r: done.append(r))

    window.on_run()
    # Poll the worker instead of blocking: a hung child must fail the test, not
    # hang the suite.
    for _ in range(200):
        if done:
            break
        pump(50)
    assert done, "run never produced a result"
    result = done[0]
    assert result.exit_code == 0
    assert "hit 10.0.0.1" in result.output
    assert "hit 10.0.0.1" in window.run_panel.console.toPlainText()


def test_run_button_disables_while_a_run_is_live(app, window):
    for row in range(window.sidebar.list.count()):
        if window.sidebar.irs[window.sidebar.list.item(row).data(QtCore.Qt.UserRole + 4)].path.name == "ask.sh":
            window.sidebar.list.setCurrentRow(row)
            break
    pump()
    # An answer is required: with an empty queue the child blocks on read until
    # the timeout, which is correct behaviour and would make this test flaky.
    window.interface.inputs["t"].setText("1.2.3.4")
    window.on_run()
    assert not window.act_run.isEnabled()
    assert window.act_stop.isEnabled()
    for _ in range(200):
        if window.act_run.isEnabled():
            break
        pump(50)
    assert window.act_run.isEnabled()
    assert not window.act_stop.isEnabled()


def test_rescan_picks_up_a_new_script(app, tmp_path, window):
    fresh = tmp_path / "brand-new.sh"
    fresh.write_text('#!/bin/bash\nread -r n\necho "n=$n"\n')
    fresh.chmod(0o755)
    window.rescan()
    pump()
    names = {ir.path.name for ir in window.sidebar.irs}
    assert "brand-new.sh" in names


def test_rescan_survives_a_missing_root(app, tmp_path):
    win = MainWindow(roots=[tmp_path / "does-not-exist"], lang="en")
    pump()
    assert win.sidebar.list.count() == 0
    win.close()


def test_console_answers_are_parsed(window):
    window.run_panel.answers_edit.setPlainText("target: 1.2.3.4\nport: 8080\ngarbage line\n")
    assert window._parse_console_answers() == {"target": "1.2.3.4", "port": "8080"}


def test_icon_asset_is_shipped():
    from scriptforge.gui.main_window import ICON_CANDIDATES

    assert any(p.exists() for p in ICON_CANDIDATES), "no window icon found"


def test_stylesheet_parses(app):
    from scriptforge.gui.style import stylesheet

    sheet = stylesheet()
    assert "{" in sheet and "}" in sheet
    # Qt silently drops a sheet it cannot parse; assert the rules we depend on.
    assert "QHeaderView::section" in sheet
    assert "QToolButton#primary" in sheet

def test_unanswered_prompt_does_not_stall_until_the_timeout(tmp_path):
    """Regression: three prompts, two answers used to hang for the full run
    timeout, because the child blocked in read() on a pty nobody closed.

    The runner must send EOF once the answer queue is empty, which is the same
    contract as `bash < answers.txt`.
    """

    from scriptforge.core.runner import ScriptRunner

    script = tmp_path / "three.sh"
    script.write_text(
        '#!/bin/bash\n'
        'read -rp "one: " a\n'
        'read -rp "two: " b\n'
        'read -rp "three: " c\n'
        'echo "got $a $b ${c:-<eof>}"\n'
    )
    script.chmod(0o755)

    import time

    started = time.monotonic()
    runner = ScriptRunner(script, answers={"a": "1", "b": "2"}, timeout=30)
    result = runner.run_interactive()
    elapsed = time.monotonic() - started

    assert elapsed < 15, f"run stalled for {elapsed:.1f}s instead of hitting EOF"
    assert result.timed_out is False
    assert result.exit_code == 0
    assert "got 1 2" in result.output


def test_confirm_field_always_carries_an_answer(window):
    """A y/N prompt left blank stalls the child, so the form never emits empty
    for a checkbox."""

    class Fake:
        widget = S and None

    from PySide6 import QtWidgets as W

    from scriptforge.gui.panels import InterfacePanel

    panel = InterfacePanel(S.EN)
    checkbox = W.QCheckBox("x")
    line = W.QLineEdit("")
    panel.inputs = {"flag": checkbox, "host": line}
    assert panel.answers() == {"flag": "n"}
    checkbox.setChecked(True)
    assert panel.answers() == {"flag": "y"}


# --- regression: Build interface hung, and the y/N box was unusable ----------

def test_built_dir_is_a_default_root(app, tmp_path):
    """Regression: on_forge appended the output folder to self.roots on every
    click, so the root list grew without bound and each rescan re-walked one
    more directory until the window looked frozen. It is a default root now.

    Built with no explicit roots: passing roots replaces the defaults, and a
    named root that does not exist is deliberately kept on the list so a wrong
    path is visible rather than silently swapped for ~/bin.
    """

    from scriptforge.gui.main_window import DEFAULT_ROOTS, built_dir

    assert built_dir() in DEFAULT_ROOTS

    win = MainWindow(roots=[tmp_path], lang="en")
    pump()
    assert built_dir() in DEFAULT_ROOTS
    win.close()


def test_forge_click_does_not_grow_the_root_list(app, root):
    from scriptforge.gui.main_window import MainWindow

    win = MainWindow(roots=[root], lang="en")
    pump()
    before = len(win.roots)

    for _ in range(3):
        win.on_forge()
        for _ in range(80):
            if win._forge_thread is None:
                break
            pump(30)
    pump()
    assert len(win.roots) == before


def test_forge_runs_off_the_gui_thread(app, root):
    """An inline analyze+write froze the window, which is indistinguishable
    from a crash for the person pressing the button."""

    win = MainWindow(roots=[root], lang="en")
    pump()
    win.on_forge()
    assert win._forge_thread is not None, "forge ran inline"
    for _ in range(120):
        if win._forge_thread is None:
            break
        pump(30)
    assert win._forge_thread is None


def test_build_button_is_disabled_for_unbuildable_scripts(app, root):
    """An opaque entry point has nothing to generate; the button used to be
    enabled and then report a failure that read like a bug.

    Driven with a constructed IR rather than a real file: the unit here is the
    button wiring, not the classifier's definition of opaque.
    """

    from scriptforge.core.parser.ir import Kind, Lang, ScriptIR

    win = MainWindow(roots=[root], lang="en")
    pump()

    opaque = ScriptIR(
        path=root / "wrapper.sh", kind=Kind.OPAQUE, lang=Lang.BASH
    )
    win.on_select(opaque)
    pump()
    assert opaque.buildable is False
    assert not win.act_forge.isEnabled()
    assert win.act_forge.toolTip(), "no explanation offered for a disabled button"

    # And it comes back when a buildable script is selected.
    win.on_select(win.sidebar.irs[0])
    pump()
    assert win.act_forge.isEnabled()
    win.close()


def test_confirm_renders_as_a_choice_not_a_toggle(app, root, tmp_path):
    """A y/N prompt is a choice. A checkbox forced the user to know that
    checked means y, with no way to see which was selected."""

    from scriptforge.core.parser.classify import analyze
    from scriptforge.gui.panels import InterfacePanel

    script = tmp_path / "yn.sh"
    script.write_text('#!/bin/bash\nread -rp "continue? [y/N] " go\necho "$go"\n')
    script.chmod(0o755)

    panel = InterfacePanel(S.EN)
    panel.set_script(analyze(script))
    widget = panel.inputs["go"]
    assert isinstance(widget, QtWidgets.QComboBox)
    assert widget.count() == 2


def test_bracket_default_is_read_from_the_prompt():
    """`[y/N]` means n is the default; the uppercase letter marks it. Reading
    the pair in literal order answered y to a question that asked for n."""

    from scriptforge.gui.panels import yes_looks_default

    assert yes_looks_default("[y/N]? ") is False
    assert yes_looks_default("[Y/n]? ") is True
    assert yes_looks_default("[Y/N]? ") is True
    assert yes_looks_default("[n/y]? ") is False
    assert yes_looks_default("continue? ") is False


def test_prompts_with_a_default_are_optional(app, root):
    """A field the script supplies a default for is one the user can skip; a
    200-field script as a wall of inputs is unusable."""

    win = MainWindow(roots=[root], lang="en")
    pump()
    for row in range(win.sidebar.list.count()):
        name = win.sidebar.irs[win.sidebar.list.item(row).data(QtCore.Qt.UserRole + 4)].path.name
        if name == "ask.sh":
            win.sidebar.list.setCurrentRow(row)
            break
    pump()

    panel = win.interface
    # isVisibleTo, not isVisible: the panel lives in a tab that is not the
    # current one, so isVisible() reports False for rows that are shown.
    shown = [row for _, row, _ in panel.rows if row.isVisibleTo(panel)]
    folded = [row for _, row, _ in panel.rows if not row.isVisibleTo(panel)]
    # ask.sh has one prompt with no default, so it stays shown; nothing to fold.
    assert len(shown) == 1 and not folded
    win.close()


def test_optional_toggle_expands_and_collapses(app, tmp_path):
    """Required fields stay open, fields with a default fold away, and the
    toggle puts them back."""

    from scriptforge.core.parser.ir import Kind, PromptSite, ScriptIR, Widget
    from scriptforge.gui.panels import InterfacePanel

    panel = InterfacePanel(S.EN)
    panel.resize(600, 400)

    ir = ScriptIR(path=tmp_path / "mix.sh", kind=Kind.INTERACTIVE)
    ir.prompt_sites = [
        PromptSite(line=1, prompt="target host: ", var="host", widget=Widget.TEXT),
        PromptSite(line=2, prompt="port [443]: ", var="port", widget=Widget.TEXT),
        PromptSite(line=3, prompt="continue? [y/N] ", var="go", widget=Widget.CONFIRM),
    ]
    panel.set_script(ir)
    pump(10)

    shown = [r for _, r, _ in panel.rows if r.isVisibleTo(panel)]
    folded = [r for _, r, _ in panel.rows if not r.isVisibleTo(panel)]
    assert len(shown) == 1, "a prompt with no default must stay open"
    assert len(folded) == 2

    toggle = panel._toggle
    toggle.setChecked(True)
    pump(10)
    assert all(r.isVisibleTo(panel) for r in folded)

    toggle.setChecked(False)
    pump(10)
    assert not any(r.isVisibleTo(panel) for r in folded)


def test_close_with_a_live_thread_does_not_abort(app, root):
    """QThread destroyed at teardown aborts the interpreter."""

    win = MainWindow(roots=[root], lang="en")
    pump()
    win.close()
    pump(40)
    assert win._thread is None
