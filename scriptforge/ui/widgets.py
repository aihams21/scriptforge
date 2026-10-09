"""Generated UI widgets.

The shape of a script's UI is decided entirely by its ScriptIR, so two
scripts never look the same. A script with prompts gets a form; a script with
subcommands gets a menu; a curses tool gets an embedded terminal.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Checkbox,
    Footer,
    Header,
    Input,
    Label,
    OptionList,
    RichLog,
    Rule,
    Select,
    Static,
    TextArea,
)
from textual.widgets.option_list import Option  # noqa: F401 - used by callers

from ..core.parser.ir import Kind, PromptSite, ScriptIR, Widget
from . import theme


class Confirm(ModalScreen[bool]):
    """A yes/no dialog built on top of a script's y/n prompt."""

    def __init__(self, message: str, title: str = "Confirm"):
        super().__init__()
        self._message = message
        self._title = title

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box", classes="dialog"):
            yield Label(self._title, classes="dialog-title")
            yield Static(self._message, classes="dialog-body")
            with Horizontal(classes="dialog-row"):
                yield Button("Yes (y)", variant="primary", id="yes")
                yield Button("No (n)", variant="default", id="no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")


class ScriptScreen(ModalScreen[dict[str, Any]]):
    """The generated form for one script.

    Renders a widget per IR field. Returns {values, subcommand, argv_flags}.
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, ir: ScriptIR, answer_order: list[str] | None = None):
        super().__init__()
        self.ir = ir
        self.answer_order = answer_order or []
        self.values: dict[str, str] = {}
        self.subcommand: str | None = None

    # ------------------------------------------------------------- compose

    def compose(self) -> ComposeResult:
        ir = self.ir
        yield Header(show_clock=False)
        with VerticalScroll(id="forge-body"):
            yield Static(theme.banner(), classes="brand")
            yield Rule(line_style="solid")
            yield Static(f"[b]{ir.name}[/b]  ·  {ir.description or 'no description'}", classes="title")
            yield Static(f"kind {ir.kind.value}", classes=f"meta kind-{ir.kind.value}")
            yield Static(
                f"lang {ir.lang.value}   ·   {ir.line_count} lines   ·   parsed via {ir.parse_mode}",
                classes="meta",
            )

            for warning in ir.warnings[:3]:
                yield Static(f"⚠ {warning}", classes="warning")

            if ir.usage_text:
                yield Static("[b]USAGE[/b]\n" + ir.usage_text, classes="usage")

            if ir.detected_tools:
                yield Static("[b]TOOLS[/b]  " + " · ".join(ir.detected_tools), classes="tools")

            if ir.subcommands:
                yield Static("[b]SUBCOMMAND[/b]", classes="section")
                yield Select(
                    [(s.name, s.name) for s in ir.subcommands],
                    prompt="choose a mode…",
                    id="subcommand",
                )

            if ir.prompt_sites:
                yield Static("[b]FIELDS[/b]", classes="section")
                for site in ir.prompt_sites:
                    yield from self._compose_field(site)

            if ir.positional_args:
                yield Static("[b]POSITIONAL ARGUMENTS[/b]", classes="section")
                for arg in ir.positional_args:
                    yield Label(arg.help or arg.name, classes="field-label")
                    yield Input(placeholder=arg.name, id=f"arg_{arg.name}")

            if ir.flags:
                yield Static("[b]FLAGS[/b]", classes="section")
                for flag in ir.flags:
                    yield Checkbox(flag.help or flag.long, id=f"flag_{flag.short}")

            yield Static(" ", classes="spacer")
            with Horizontal(classes="actions"):
                yield Button("Run ▶", variant="primary", id="run")
                yield Button("Cancel ✕", variant="default", id="cancel")
        yield Footer()

    def _compose_field(self, site: PromptSite):
        label = site.prompt if site.prompt.strip() else site.var
        if site.widget is Widget.CHOICE and site.choices:
            yield Label(label, classes="field-label")
            yield Select(
                [(c, c) for c in site.choices],
                prompt=f"{label}…",
                id=f"site_{site.var}_{site.line}",
            )
        elif site.widget is Widget.CONFIRM:
            yield Checkbox(label, id=f"site_{site.var}_{site.line}")
        else:
            yield Label(label, classes="field-label")
            yield Input(
                password=site.widget is Widget.SECRET,
                placeholder=site.default or site.var,
                id=f"site_{site.var}_{site.line}",
            )

    # ------------------------------------------------------------- events

    def on_mount(self) -> None:
        if self.ir.subcommands:
            try:
                self.query_one("#subcommand", Select).focus()
            except Exception:  # noqa: BLE001
                pass

    def _collect(self) -> dict[str, Any]:
        values: dict[str, str] = {}
        flags: list[str] = []

        for site in self.ir.prompt_sites:
            key = f"site_{site.var}_{site.line}"
            try:
                widget = self.query_one(f"#{key}")
            except Exception:  # noqa: BLE001
                continue
            if isinstance(widget, Select):
                values[site.var] = str(widget.value)
            elif isinstance(widget, Checkbox):
                values[site.var] = "y" if widget.value else "n"
            elif isinstance(widget, Input):
                values[site.var] = widget.value

        for arg in self.ir.positional_args:
            try:
                inp = self.query_one(f"#arg_{arg.name}", Input)
                if inp.value:
                    values[arg.name] = inp.value
            except Exception:  # noqa: BLE001
                pass

        for flag in self.ir.flags:
            try:
                cb = self.query_one(f"#flag_{flag.short}", Checkbox)
                if cb.value:
                    flags.append(flag.short)
            except Exception:  # noqa: BLE001
                pass

        sub = None
        if self.ir.subcommands:
            try:
                sel = self.query_one("#subcommand", Select)
                sub = str(sel.value) if sel.value is not None else None
            except Exception:  # noqa: BLE001
                sub = None

        # Preserve the script's own prompt order for PTY injection.
        ordered: dict[str, str] = {}
        for name in self.answer_order:
            if name in values:
                ordered[name] = values[name]
        for k, v in values.items():
            ordered.setdefault(k, v)

        return {"values": ordered, "flags": flags, "subcommand": sub}

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "run":
            self.dismiss(self._collect())
        elif event.button.id == "cancel":
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class RunScreen(ModalScreen[bool]):
    """Live PTY output with a kill switch.

    Owns the execution: a worker thread streams into the log, `Stop` kills the
    child, and the screen stays up until the process is actually gone.
    """

    BINDINGS = [("escape", "stop", "Stop")]

    def __init__(
        self,
        script_name: str,
        argv: list[str],
        runner: "ScriptRunner | None" = None,
        answers: dict[str, str] | None = None,
    ):
        super().__init__()
        self.script_name = script_name
        self.argv = argv
        self.runner = runner
        self.answers = answers or {}
        self.result = None
        self._killed = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="run-body"):
            yield Static(f"[b]{self.script_name}[/b]", classes="title")
            yield Static(" ".join(self.argv)[:240], classes="meta")
            yield Rule(line_style="solid")
            yield Static("[dim]starting…[/dim]", id="run-status")
            yield RichLog(id="pane", highlight=False, markup=False, wrap=True)
        with Horizontal(classes="actions"):
            yield Button("Stop ⏹", variant="error", id="stop")
            yield Button("Close", variant="default", id="close", disabled=True)
        yield Footer()

    def on_mount(self) -> None:
        if self.runner is None:
            self._finish(None)
            return
        self.run_worker(self._drive(), thread=True)

    # ------------------------------------------------------------- execution

    def _drive(self):
        from ..core.runner import ScriptRunner

        assert self.runner is not None
        pane = self.app.query_one("#pane") if hasattr(self, "app") else None
        chunks: list[str] = []

        def sink(chunk: str) -> None:
            chunks.append(chunk)
            self.call_from_thread(self._write, chunk)

        if self.answers:
            order = list(self.answers.keys())
            result = self.runner.run_interactive(answer_order=order, on_output=sink)
        else:
            result = self.runner.run_plain(on_output=sink)

        if self._killed:
            result.timed_out = True
        self.result = result
        self.call_from_thread(self._finish, result)

    def _write(self, chunk: str) -> None:
        try:
            self.query_one("#pane", RichLog).write(chunk)
        except Exception:  # noqa: BLE001 - screen may be gone
            pass

    def _finish(self, result) -> None:
        status = self.query_one("#run-status")
        if result is None:
            status.update("[dim]no runner attached[/dim]")
        else:
            colour = theme.OK if result.exit_code == 0 else theme.CRIT
            note = " (stopped)" if self._killed else ""
            status.update(
                f"[{colour}]exit {result.exit_code}[/] in {result.duration_s:.1f}s "
                f"via {result.mode}{note}"
            )
        try:
            self.query_one("#stop", Button).disabled = True
            self.query_one("#close", Button).disabled = False
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------- events

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "stop":
            self._kill()
        elif event.button.id == "close":
            self.dismiss(True)

    def _kill(self) -> None:
        self._killed = True
        try:
            self.query_one("#run-status", Static).update("[warn]stopping…[/warn]")
        except Exception:  # noqa: BLE001
            pass
        if self.runner is not None and getattr(self.runner, "_child", None) is not None:
            try:
                self.runner._child.terminate(force=True)  # noqa: SLF001
            except Exception:  # noqa: BLE001
                pass

    def action_stop(self) -> None:
        self._kill()


CSS = """
Screen { background: #0d1117; }
.brand { color: #00d7af; margin: 1 0 0 0; }
.title { color: #c9d1d9; margin: 0 0 0 0; }
.meta { color: #6e7681; }
.section { color: #ffb800; margin-top: 1; text-style: bold; }
.field-label { color: #c9d1d9; margin: 1 0 0 0; }
.warning { color: #ffb800; }
.kind-interactive { color: #00d7af; text-style: bold; }
.kind-parametric { color: #58a6ff; text-style: bold; }
.kind-skeletal { color: #ffb800; text-style: bold; }
.kind-fullscreen { color: #ff4d6d; text-style: bold; }
.kind-opaque { color: #6e7681; text-style: bold; }
.kind-unknown { color: #6e7681; text-style: bold; }
.usage { color: #8b949e; background: #161b22; padding: 1 2; }
.tools { color: #58a6ff; }
.spacer { height: 1; }
.actions { align: center middle; height: auto; padding: 1 0; }
.actions Button { margin: 0 2; }
#forge-body { padding: 0 2; }
#pane { height: 1fr; border: round #30363d; background: #0d1117; }
#confirm-box {
    background: #161b22; border: round #00d7af; padding: 1 2;
    width: 60; height: auto;
}
.dialog-title { color: #00d7af; text-style: bold; }
.dialog-body { margin: 1 0; }
.dialog-row { align: center middle; }
"""