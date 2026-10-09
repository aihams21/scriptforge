"""The scriptforge TUI: browse scripts, forge an interface, run it."""

from __future__ import annotations

import os
from pathlib import Path

from textual.app import App, ComposeResult
from textual import work
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Header, Input, OptionList, Static, TextArea
from textual.widgets.option_list import Option

from ..core.parser import Kind, ScriptIR, analyze, scan_directory
from ..core.rewriter import rewrite
from ..core.runner import ScriptRunner
from ..core.vault import Vault
from . import theme
from .widgets import CSS, Confirm, RunScreen, ScriptScreen

DEFAULT_ROOTS = [
    Path.home() / "bin",
    Path.home() / ".local" / "bin",
    Path("/usr/local/bin"),
    Path("/usr/bin"),
]

MIN_LINES = 3


class ScriptForge(App):
    CSS = CSS + """
    #body { padding: 0 1; }
    #left { width: 46; border-right: solid #30363d; }
    #right { padding: 0 2; }
    #roots { height: auto; margin-bottom: 1; }
    #filter { margin-bottom: 1; }
    OptionList { background: #0d1117; height: 1fr; }
    #detail-title { color: #00d7af; text-style: bold; }
    #detail-body { height: 1fr; border: round #30363d; padding: 1 2; }
    .dim { color: #6e7681; }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("/", "focus_filter", "Search"),
        ("r", "refresh", "Rescan"),
        ("enter", "forge", "Forge UI"),
    ]

    def __init__(self, roots: list[Path] | None = None, **kw):
        super().__init__(**kw)
        self.roots = [Path(r) for r in (roots or DEFAULT_ROOTS)]
        self.irs: list[ScriptIR] = []
        self.selected: ScriptIR | None = None
        self._last_result = None
        self._root_by_id: dict[str, Path] = {}
        self.vault = Vault()

    # ------------------------------------------------------------- compose

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="body"):
            yield Static(theme.banner(), classes="brand")
            with Horizontal(id="roots"):
                for i, r in enumerate(self.roots[:4]):
                    self._root_by_id[f"root_{i}"] = r
                    yield Button(str(r), variant="default", id=f"root_{i}")
            yield Input(placeholder="filter scripts…  ( / to focus )", id="filter")
            with Horizontal():
                with Vertical(id="left"):
                    yield OptionList(id="list")
                with Vertical(id="right"):
                    yield Static("← pick a script", id="detail-title")
                    yield TextArea("", id="detail-body", read_only=True)
        yield Footer()

    def on_mount(self) -> None:
        self.scan_all()
        try:
            self.query_one("#list", OptionList).focus()
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------- scanning

    def _modal_open(self) -> bool:
        """True while a dialog is stacked on top of the main screen.

        App-level key bindings stay live while a modal is up, so every action
        that touches main-screen widgets has to bail out here. Otherwise a
        stray keypress reaches into a widget that is not mounted and kills
        the app.
        """
        return len(self.screen_stack) > 1

    def scan_all(self) -> None:
        self.irs = []
        seen: set[Path] = set()
        for root in self.roots:
            if not root.is_dir():
                continue
            for ir in scan_directory(root):
                real = ir.path
                if real in seen or ir.kind is Kind.UNKNOWN:
                    continue
                seen.add(real)
                self.irs.append(ir)
        self.irs.sort(key=lambda i: (i.kind.value, i.name))
        self._populate()

    def scan_root(self, root: Path) -> None:
        self.roots = [root] + [r for r in self.roots if r != root]
        self.scan_all()

    def _populate(self) -> None:
        optlist = self.query_one("#list", OptionList)
        optlist.clear_options()
        needle = self.query_one("#filter", Input).value.strip().lower()
        shown = 0
        for ir in self.irs:
            if needle and needle not in ir.name.lower():
                continue
            shown += 1
            optlist.add_option(
                Option(
                    f"{ir.name}  [{ir.kind.value}]",
                    id=str(ir.path),
                )
            )
        if shown == 0:
            self.notify("no scripts matched", severity="warning")

    # ------------------------------------------------------------- events

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "filter":
            self._populate()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "filter":
            self.action_forge()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id and event.button.id in self._root_by_id:
            self.scan_root(self._root_by_id[event.button.id])
        elif event.button.id == "forged":
            self.action_forge()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        path = Path(str(event.option.id))
        try:
            ir = analyze(path)
        except Exception as exc:  # noqa: BLE001
            self.notify(f"analysis failed: {exc}", severity="error")
            return
        self.selected = ir
        self._show_detail(ir)

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        """Arrow-key navigation: refresh the detail pane as the cursor moves."""
        option_id = getattr(event.option, "id", None)
        if not option_id:
            return
        try:
            ir = analyze(Path(str(option_id)))
        except Exception:  # noqa: BLE001
            return
        self.selected = ir
        self._show_detail(ir)

    def _show_detail(self, ir: ScriptIR) -> None:
        self.query_one("#detail-title", Static).update(f"{ir.name}  [{ir.kind.value}]")
        lines = [
            f"path      {ir.path}",
            f"kind      {ir.kind.value}   lang {ir.lang.value}   parser {ir.parse_mode}",
            f"size      {ir.line_count} lines",
            "",
        ]
        if ir.description:
            lines.append(f"about     {ir.description}")
        if ir.detected_tools:
            lines.append(f"tools     {' · '.join(ir.detected_tools)}")
        if ir.positional_args:
            lines.append(f"args      {', '.join(a.name for a in ir.positional_args)}")
        if ir.subcommands:
            lines.append(f"modes     {', '.join(s.name for s in ir.subcommands)}")
        if ir.prompt_sites:
            lines.append("")
            lines.append("PROMPTS")
            for p in ir.prompt_sites[:14]:
                ch = ", ".join(p.choices[:4])
                suffix = f"  [{ch}]" if ch else ""
                lines.append(f"  L{p.line:<5} {p.prompt}  ({p.widget.value}){suffix}")
            if len(ir.prompt_sites) > 14:
                lines.append(f"  … +{len(ir.prompt_sites) - 14} more")
        if ir.warnings:
            lines.append("")
            for w in ir.warnings[:4]:
                lines.append(f"⚠ {w}")
        if ir.kind is Kind.SKELETAL:
            lines.append("")
            lines.append("→ Forge will generate an interactive wrapper in")
            lines.append(f"  {Path.home() / '.scriptforge' / 'built'}")
            lines.append("  (original file untouched)")
        self.query_one("#detail-body", TextArea).text = "\n".join(lines)

    # ------------------------------------------------------------- actions

    def action_focus_filter(self) -> None:
        if self._modal_open():
            return
        self.query_one("#filter", Input).focus()

    def action_refresh(self) -> None:
        if self._modal_open():
            return
        self.scan_all()
        self.notify(f"rescanned · {len(self.irs)} scripts", title="scriptforge")

    @work
    async def action_forge(self) -> None:
        ir = self.selected
        if ir is None:
            self.notify("select a script first", severity="warning")
            return

        if ir.kind is Kind.SKELETAL:
            ok = await self.push_screen_wait(Confirm(
                f"'{ir.name}' has no interface of its own.\n\n"
                f"Generate an interactive wrapper in\n"
                f"  {Path.home() / '.scriptforge' / 'built'}/\n\n"
                f"The original file is never modified.",
                title="Re-program script?",
            ))
            if not ok:
                return
            result = rewrite(ir, force=True)
            if not result.ok:
                self.notify(result.message, severity="error")
                return
            self.notify(f"wrote {result.generated.name}", title="forged")
            ir = analyze(result.generated)

        order = [s.var for s in ir.prompt_sites]
        collected = await self.push_screen_wait(ScriptScreen(ir, order))
        if collected is None:
            return

        answers = collected["values"]
        argv: list[str] = []
        if collected.get("subcommand"):
            argv.append(collected["subcommand"])
        argv.extend(collected.get("flags", []))
        for name in order:
            value = answers.get(name)
            if value:
                argv.append(value)

        runner = ScriptRunner(ir.path, answers=answers, timeout=600)
        preview = runner.preview()
        screen = RunScreen(ir.name, preview, runner, answers)
        closed = await self.push_screen_wait(screen)

        result = screen.result
        if closed is not True or result is None:
            if screen._error:
                self.notify(screen._error, title="run failed", severity="error")
            return

        self._last_result = result
        self.vault.log_run(
            str(ir.path), ir.kind.value, result.argv,
            result.exit_code, result.duration_s, result.output, answers,
        )
        self.notify(
            f"{ir.name} → exit {result.exit_code} ({result.duration_s:.1f}s)  logged",
            title="run finished",
            severity="information" if result.ok else "warning",
        )