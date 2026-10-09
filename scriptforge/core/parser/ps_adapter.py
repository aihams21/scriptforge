"""PowerShell -> ScriptIR adapter.

Windows users run scriptforge natively, so it has to understand `.ps1`:
`param()` blocks give arguments, `Read-Host` gives prompts. Also handles
`.bat`/`.cmd` by recognising the interactive `set /p` prompt.
"""

from __future__ import annotations

import re
from pathlib import Path

from .ir import (
    ArgSpec,
    FlagSpec,
    Kind,
    Lang,
    OutputShape,
    PromptSite,
    ScriptIR,
    SubCommand,
    Widget,
    guess_widget,
    humanize,
)

from .bash_adapter import TOOL_SHAPES, FULLSCREEN_TOOLS, _choices_from_surround

# param([string]$Target, [int]$Port = 80, [switch]$Verbose)
PARAM_RE = re.compile(
    r"param\s*\((?P<args>[^)]*)\)", re.IGNORECASE | re.DOTALL
)
TYPE_MAP = {
    "string": "text", "int": "number", "switch": "switch",
    "bool": "switch", "string[]": "text", "object": "text",
}
READHOST_RE = re.compile(
    r"\$(?P<var>[\w]+)\s*=\s*Read-Host\s+(?:-\w+\s+)*(?P<q>['\"](?P<text>[^'\"]*)['\"])?",
    re.IGNORECASE,
)
CHOICE_RE = re.compile(r"\$(?P<var>\w+)\s*=\s*Read-Host\s+-Choices\s*", re.IGNORECASE)
SETP_RE = re.compile(r"set\s+/p\s+(?P<var>[\w]+)=(?P<text>[^\r\n]*)", re.IGNORECASE)

PS_EXT = {".ps1", ".psm1"}
BAT_EXT = {".bat", ".cmd"}


def analyze_powershell(path: Path) -> ScriptIR:
    text = path.read_text(errors="replace")
    lines = text.splitlines()
    ir = ScriptIR(path=path, lang=Lang.POWERSHELL, line_count=len(lines))
    ir.description = _ps_comment(lines)

    detected = [t for t in TOOL_SHAPES if re.search(rf"(?<![\w-]){re.escape(t)}(?![\w-])", text)]
    ir.detected_tools = detected
    from .ir import OutputHint

    ir.output_hints = [
        OutputHint(tool=t, shape=TOOL_SHAPES.get(t, OutputShape.TEXT), reason="known tool")
        for t in detected
    ]

    _scan(text, lines, ir)

    seen, subs = set(), []
    for s in ir.subcommands:
        if s.name not in seen:
            seen.add(s.name)
            subs.append(s)
    ir.subcommands = subs
    seenf, flags = set(), []
    for f in ir.flags:
        if f.short not in seenf:
            seenf.add(f.short)
            flags.append(f)
    ir.flags = flags

    if detected and any(t in FULLSCREEN_TOOLS for t in detected):
        ir.kind = Kind.FULLSCREEN
    elif ir.prompt_sites:
        ir.kind = Kind.INTERACTIVE
    elif ir.positional_args or ir.flags:
        ir.kind = Kind.PARAMETRIC
    else:
        ir.kind = Kind.SKELETAL
    ir.parse_mode = "scan"
    return ir


def analyze_batch(path: Path) -> ScriptIR:
    """Batch has almost no recoverable interface: labels, `set /p`, and %1..%9."""
    text = path.read_text(errors="replace")
    lines = text.splitlines()
    ir = ScriptIR(path=path, lang=Lang.BATCH, line_count=len(lines))
    ir.description = _ps_comment(lines)

    for idx, line in enumerate(lines, start=1):
        m = SETP_RE.search(line)
        if m:
            ir.prompt_sites.append(
                PromptSite(
                    line=idx,
                    prompt=m.group("text").strip() or humanize(m.group("var")),
                    var=m.group("var"),
                    widget=guess_widget(m.group("var"), m.group("text")),
                    choices=_choices_from_surround(lines, idx),
                )
            )
        m_choice = re.match(r"\s*:?(\w+)\s*$", line.strip())
        if re.match(r"^\s*(if|choice)\s+/[cim]", line, re.I):
            ir.prompt_sites.append(
                PromptSite(
                    line=idx,
                    prompt=humanize(m_choice.group(1) if m_choice else "choice"),
                    var=(m_choice.group(1) if m_choice else "choice"),
                    widget=Widget.CHOICE,
                    choices=_choices_from_surround(lines, idx),
                )
            )

    used = set(re.findall(r"%(\d)", text))
    for i in range(1, 10):
        if str(i) in used:
            ir.positional_args.append(ArgSpec(index=i - 1, name=f"arg{i}"))

    seen, subs = set(), []
    for s in _batch_labels(lines):
        if s.name not in seen:
            seen.add(s.name)
            subs.append(s)
    ir.subcommands = subs

    if ir.prompt_sites:
        ir.kind = Kind.INTERACTIVE
    elif ir.subcommands or ir.positional_args:
        ir.kind = Kind.PARAMETRIC
    else:
        ir.kind = Kind.SKELETAL
    ir.parse_mode = "scan"
    return ir


# --------------------------------------------------------------------------- helpers


def _scan(text: str, lines: list[str], ir: ScriptIR) -> None:
    m = PARAM_RE.search(text)
    if m:
        body = m.group("args")
        # split on commas that are not inside quotes or brackets
        depth = 0
        quoted = False
        chunk = []
        parts = []
        for ch in body:
            if ch == "'":
                quoted = not quoted
            if not quoted:
                if ch in "([{":
                    depth += 1
                elif ch in ")]}":
                    depth -= 1
                if ch == "," and depth == 0:
                    parts.append("".join(chunk))
                    chunk = []
                    continue
            chunk.append(ch)
        parts.append("".join(chunk))

        for part in parts:
            part = part.strip()
            if not part:
                continue
            tm = re.match(r"\[?\s*(?:(\w+)\s*)?\]\s*\$(\w+)(?:\s*=\s*(.+))?$", part)
            if not tm:
                continue
            ptype = (tm.group(1) or "string").lower()
            name = tm.group(2)
            default = (tm.group(3) or "").strip()
            if ptype in ("switch", "bool"):
                ir.flags.append(
                    FlagSpec(short=f"-{name}", long=f"-{name}", takes_value=False, help=humanize(name))
                )
            else:
                ir.positional_args.append(
                    ArgSpec(index=len(ir.positional_args), name=name, help=f"{ptype} {default}".strip())
                )

    for idx, line in enumerate(lines, start=1):
        m = READHOST_RE.search(line)
        if m:
            question = (m.group("text") or humanize(m.group("var"))).strip()
            widget = guess_widget(m.group("var"), question)
            if CHOICE_RE.search(line):
                widget = Widget.CHOICE
            ir.prompt_sites.append(
                PromptSite(
                    line=idx,
                    prompt=question,
                    var=m.group("var"),
                    widget=widget,
                    choices=_choices_from_surround(lines, idx),
                )
            )


def _batch_labels(lines: list[str]) -> list[SubCommand]:
    out: list[SubCommand] = []
    for line in lines[:80]:
        m = re.match(r"^\s*:([a-zA-Z][\w-]*)\s*$", line)
        if m:
            out.append(SubCommand(name=m.group(1), help=humanize(m.group(1))))
        else:
            m2 = re.match(r"^\s*(?:goto|echo)\s+:?([a-zA-Z][\w-]*)\s*$", line, re.I)
            if m2:
                out.append(SubCommand(name=m2.group(1), help=humanize(m2.group(1))))
    return out


def _ps_comment(lines: list[str]) -> str:
    in_block = False
    for lineno, line in enumerate(lines[:15]):
        s = line.strip()
        if lineno == 0 and s.startswith("#!"):
            continue
        if s.startswith("<#"):
            in_block = True
            body = s.lstrip("<#").strip()
            if body and not set(body) <= set("═=-─━*#·."):
                return body
            continue
        if in_block:
            if s.endswith("#>"):
                return s.rstrip("#>").strip()
            if s:
                return s
            continue
        if s.startswith("#") and len(s) > 2:
            body = s.lstrip("# ").strip()
            if body and not set(body) <= set("═=-─━*#·."):
                return body
    return ""