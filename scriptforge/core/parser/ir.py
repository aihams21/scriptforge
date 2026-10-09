"""Intermediate Representation shared by every language adapter.

The whole point of this module: the UI layer never learns whether the source
script was bash or python. Both adapters emit a `ScriptIR`, and everything
downstream (rewriter, runner, textual widgets) consumes only that.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any


class Kind(str, Enum):
    """How a script must be wrapped."""

    INTERACTIVE = "interactive"  # asks the user questions mid-run
    PARAMETRIC = "parametric"  # subcommands + positional args
    SKELETAL = "skeletal"  # no interface at all -> needs rewriting
    FULLSCREEN = "fullscreen"  # curses/TUI -> embed the raw PTY
    OPAQUE = "opaque"  # delegates elsewhere (package shim) -> freeform argv
    UNKNOWN = "unknown"


class Lang(str, Enum):
    BASH = "bash"
    PYTHON = "python"
    POWERSHELL = "powershell"
    BATCH = "batch"
    UNKNOWN = "unknown"


class Widget(str, Enum):
    """Which control best represents a prompt site."""

    TEXT = "text"
    CHOICE = "choice"
    CONFIRM = "confirm"
    SECRET = "secret"


class OutputShape(str, Enum):
    TABLE = "table"
    TEXT = "text"
    JSON = "json"


def humanize(name: str) -> str:
    """`target_dir` -> `Target dir`. Used when a script gives no prompt text."""
    cleaned = (name or "").strip().strip("_").replace("-", "_")
    if not cleaned:
        return "Value"
    parts = [p for p in cleaned.split("_") if p]
    if not parts:
        return "Value"
    first = parts[0]
    first = first[0].upper() + first[1:]
    rest = " ".join(p if len(p) <= 2 else p[0].upper() + p[1:] for p in parts[1:])
    return f"{first} {rest}".strip()


def guess_widget(name: str, prompt: str = "") -> Widget:
    blob = f"{name} {prompt}".lower()
    if any(k in blob for k in ("pass", "password", "secret", "token", "key", "pin")):
        return Widget.SECRET
    if re_bool(blob):
        return Widget.CONFIRM
    return Widget.TEXT


def re_bool(blob: str) -> bool:
    if any(k in blob for k in ("y/n", "(y/n)", "[y/n]", "yes/no", "confirm", "proceed", "continue")):
        return True
    if any(k in blob for k in ("choice", "select", "option", "mode")):
        return True
    return False


@dataclass
class PromptSite:
    """A single place where the script stops and waits for a human."""

    line: int
    prompt: str  # human readable question
    var: str  # shell/ python variable being filled
    widget: Widget = Widget.TEXT
    choices: list[str] = field(default_factory=list)
    default: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["widget"] = self.widget.value
        return d


@dataclass
class ArgSpec:
    """A positional argument (`$1`, `sys.argv[1]`, argparse positional)."""

    index: int
    name: str
    help: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FlagSpec:
    """A named switch (`getopts`, `argparse` optional, `sys.argv` flags)."""

    short: str
    long: str
    takes_value: bool = False
    help: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SubCommand:
    """A named mode of the script (`case $1 in ... esac`, argparse subparsers)."""

    name: str
    help: str = ""
    args: list[ArgSpec] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["args"] = [a.to_dict() for a in self.args]
        return d


@dataclass
class OutputHint:
    """What kind of output to expect, so the UI can render it well."""

    tool: str
    shape: OutputShape = OutputShape.TEXT
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["shape"] = self.shape.value
        return d


@dataclass
class ScriptIR:
    """Everything the UI needs to know about one script."""

    path: Path
    kind: Kind = Kind.UNKNOWN
    lang: Lang = Lang.UNKNOWN
    shebang: str = ""
    line_count: int = 0

    prompt_sites: list[PromptSite] = field(default_factory=list)
    positional_args: list[ArgSpec] = field(default_factory=list)
    subcommands: list[SubCommand] = field(default_factory=list)
    flags: list[FlagSpec] = field(default_factory=list)
    output_hints: list[OutputHint] = field(default_factory=list)

    usage_text: str = ""
    description: str = ""
    imports: list[str] = field(default_factory=list)
    detected_tools: list[str] = field(default_factory=list)

    # filled in by the adapters
    parse_mode: str = "ast"  # "ast" or "scan" (regex fallback)
    warnings: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def needs_rewrite(self) -> bool:
        return self.kind is Kind.SKELETAL

    @property
    def buildable(self) -> bool:
        """False for things we can only launch raw (opaque / fullscreen)."""
        return self.kind not in (Kind.OPAQUE, Kind.UNKNOWN)

    @property
    def needs_pty(self) -> bool:
        return self.kind in (Kind.INTERACTIVE, Kind.FULLSCREEN, Kind.OPAQUE)

    def field_count(self) -> int:
        return len(self.prompt_sites) + len(self.positional_args) + len(self.flags)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "name": self.name,
            "kind": self.kind.value,
            "lang": self.lang.value,
            "shebang": self.shebang,
            "line_count": self.line_count,
            "prompt_sites": [p.to_dict() for p in self.prompt_sites],
            "positional_args": [a.to_dict() for a in self.positional_args],
            "subcommands": [s.to_dict() for s in self.subcommands],
            "flags": [f.to_dict() for f in self.flags],
            "output_hints": [h.to_dict() for h in self.output_hints],
            "usage_text": self.usage_text,
            "description": self.description,
            "imports": list(self.imports),
            "detected_tools": list(self.detected_tools),
            "parse_mode": self.parse_mode,
            "warnings": list(self.warnings),
        }