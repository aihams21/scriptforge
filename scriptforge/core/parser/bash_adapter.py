"""Bash -> ScriptIR adapter.

Strategy: try `bashlex` for a real AST first. If the script fails to parse
(the wild west of real shell scripts - heredocs, unbalanced quotes, tool
substitutions), fall back to a line scanner so we degrade instead of dying.
"""

from __future__ import annotations

import re
from pathlib import Path

from .ir import (
    Kind,
    Lang,
    OutputHint,
    OutputShape,
    PromptSite,
    ScriptIR,
    SubCommand,
    FlagSpec,
    ArgSpec,
    Widget,
    guess_widget,
    humanize,
)

try:
    import bashlex

    HAS_BASHLEX = True
except Exception:  # pragma: no cover
    HAS_BASHLEX = False

# bashlex is exponential on pathological input. Anything this big is a
# generated/bundled artefact (3.5M-line `firebase`), not a human script.
MAX_PARSE_LINES = 5000
MAX_PARSE_BYTES = 1_000_000
PARSE_TIMEOUT_S = 5


class _Timeout(Exception):
    pass


def _alarm(_sig, _frm):
    raise _Timeout()


def is_source_text(path: Path) -> bool:
    """Reject binaries and bundled artefacts before anyone parses them."""
    try:
        size = path.stat().st_size
    except OSError:
        return False
    if size > MAX_PARSE_BYTES:
        return False
    try:
        with path.open("rb") as fh:
            chunk = fh.read(4096)
    except OSError:
        return False
    if b"\x00" in chunk:
        return False
    return True


# Output tools we know how to render.
TOOL_SHAPES = {
    "nmap": OutputShape.TABLE,
    "masscan": OutputShape.TABLE,
    "nikto": OutputShape.TEXT,
    "sqlmap": OutputShape.TEXT,
    "gobuster": OutputShape.TEXT,
    "dirb": OutputShape.TEXT,
    "wfuzz": OutputShape.TABLE,
    "hydra": OutputShape.TEXT,
    "john": OutputShape.TEXT,
    "hashcat": OutputShape.TEXT,
    "aircrack-ng": OutputShape.TEXT,
    "airodump-ng": OutputShape.TABLE,
    "ai-replay-ng": OutputShape.TEXT,
    "bettercap": OutputShape.TEXT,
    "wpshark": OutputShape.TEXT,
    "tshark": OutputShape.TABLE,
    "ss": OutputShape.TABLE,
    "ip": OutputShape.TABLE,
    "ifconfig": OutputShape.TABLE,
}

# Commands that take over the terminal (curses / full-screen).
FULLSCREEN_TOOLS = {
    "htop", "top", "vim", "vi", "nano", "emacs", "tmux", "screen",
    "btop", "nvim", "watch", "journalctl -f", "tcpdump",
}


def analyze_bash(path: Path) -> ScriptIR:
    text = path.read_text(errors="replace")
    lines = text.splitlines()
    ir = ScriptIR(path=path, lang=Lang.BASH, line_count=len(lines))
    ir.description = _doc_comment(lines)
    ir.usage_text = _usage_from_heredoc(lines)

    detected = _detect_tools(text)
    ir.detected_tools = detected
    ir.output_hints = [
        OutputHint(tool=t, shape=TOOL_SHAPES.get(t, OutputShape.TEXT), reason="known tool")
        for t in detected
    ]

    oversized = len(lines) > MAX_PARSE_LINES
    if oversized:
        ir.warnings.append(
            f"skipped AST: {len(lines)} lines exceeds {MAX_PARSE_LINES} (generated artefact?)"
        )
        ir.parse_mode = "scan"
        _scan_bash(lines, ir)
        ir.kind = Kind.SKELETAL
        return ir

    if HAS_BASHLEX:
        import signal

        try:
            previous = signal.signal(signal.SIGALRM, _alarm)
            signal.alarm(PARSE_TIMEOUT_S)
            try:
                tree = bashlex.parse(text)
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, previous)
            _walk_bash(tree, ir, lines)
            ir.parse_mode = "ast"
        except _Timeout:
            ir.warnings.append("bashlex timed out; used line scanner")
            _scan_bash(lines, ir)
            ir.parse_mode = "scan"
        except Exception as exc:  # noqa: BLE001 - any parse error -> fallback
            ir.warnings.append(f"bashlex failed ({type(exc).__name__}); used line scanner")
            _scan_bash(lines, ir)
            ir.parse_mode = "scan"
    else:
        _scan_bash(lines, ir)
        ir.parse_mode = "scan"

    ir.prompt_sites = _dedupe_prompts(ir.prompt_sites)
    ir.subcommands = _dedupe_subcommands(ir.subcommands)
    ir.flags = _dedupe_flags(ir.flags)
    _mark_fullscreen(ir, detected)
    ir.kind = _classify(ir)
    return ir


# --------------------------------------------------------------------------- ast


def _walk_bash(node, ir: ScriptIR, lines: list[str]) -> None:
    """Recurse the bashlex tree pulling out prompts, cases, getopts."""
    kind = node.kind

    if kind == "redirect" and _redirect_is_stdin(node):
        _extract_read(node, ir, lines)
        return

    if kind == "command" and node.parts and isinstance(node.parts[0], list):
        words = node.parts[0]
        if words and getattr(words[0], "word", "").strip("'\"") == "getopts":
            _extract_getopts(words, ir)
        if words and getattr(words[0], "word", "").strip("'\"") == "select":
            _extract_select(node, ir, lines)

    if kind == "case":
        _extract_case(node, ir)
        return

    for child in getattr(node, "parts", []) or []:
        if isinstance(child, list):
            for sub in child:
                _walk_bash(sub, ir, lines)
        elif hasattr(child, "parts"):
            _walk_bash(child, ir, lines)


def _redirect_is_stdin(node) -> bool:
    for fd in getattr(node, "redirects", []) or []:
        if getattr(fd, "fd", None) == 0:
            return True
    return False


def _extract_read(node, ir: ScriptIR, lines: list[str]) -> None:
    """`read -p 'question' var` -> PromptSite. `read -r a b` -> fall back to vars."""
    parts = node.parts
    words = parts[0] if parts and isinstance(parts[0], list) else []

    prompt_text = ""
    varname = ""
    skip_next = False

    for w in words:
        word = getattr(w, "word", None)
        if word is None:
            continue
        flag, value = word, ""
        if "=" in word and word.startswith("-") and len(word) > 2:
            flag, value = word.split("=", 1)

        if flag == "-p":
            # -p "question" -> the next word is the prompt
            continue
        if flag.startswith("-") and "p" in flag.lstrip("-") and len(flag) > 1:
            # combined like -rp with inline value handled above
            pass
        if flag.startswith("-"):
            continue
        if not varname and not prompt_text and _is_quoted(word):
            prompt_text = word.strip("'\"")
        elif not varname:
            varname = word
        elif not varname:
            varname = word

    # Recompute prompt properly: bashlex splits `-p 'text'` into parts.
    prompt_text, varname = _read_args(words)

    if not varname:
        return

    for extra in varname.split():
        site = PromptSite(
            line=_safe_lineno(node),
            prompt=prompt_text or humanize(extra),
            var=extra,
            widget=guess_widget(extra, prompt_text),
            choices=_choices_from_surround(lines, _safe_lineno(node)),
        )
        ir.prompt_sites.append(site)


def _read_args(words) -> tuple[str, str]:
    """Pull (prompt, firstVar) out of a `read` argv list of bashlex words."""
    prompt = ""
    varname = ""
    i = 0
    saw_p = False
    while i < len(words):
        raw = getattr(words[i], "word", "")
        w = raw.strip("'\"")
        if saw_p and not varname and not w.startswith("-"):
            # This is the value for -p only if it wasn't consumed as var;
            # bashlex keeps -p "text" as two words.
            prompt = w
            saw_p = False
            i += 1
            continue
        if w.startswith("-") and "p" in w[1:]:
            saw_p = True
            if "=" in w:
                prompt = w.split("=", 1)[1].strip("'\"")
                saw_p = False
            i += 1
            continue
        if w.startswith("-"):
            i += 1
            continue
        if not varname:
            varname = w
        else:
            varname += " " + w
        i += 1
    return prompt, varname


def _is_quoted(word: str) -> bool:
    return len(word) >= 2 and word[0] in "'\"`"


def _safe_lineno(node) -> int:
    return getattr(node, "lineno", 0) or 0


def _extract_select(node, ir: ScriptIR, lines: list[str]) -> None:
    """`select x in a b c; do` -> a CHOICE prompt."""
    line = _safe_lineno(node)
    choices = _choices_from_surround(lines, line)
    ir.prompt_sites.append(
        PromptSite(
            line=line,
            prompt=humanize("choice"),
            var="choice",
            widget=Widget.CHOICE,
            choices=choices,
        )
    )


def _extract_case(node, ir: ScriptIR) -> None:
    """`case $1 in list) help ;; ... esac` -> subcommands."""
    parts = getattr(node, "parts", []) or []
    if not parts:
        return
    subject = " ".join(getattr(p, "word", "") for p in parts[0] if hasattr(p, "word"))
    # Only treat `case $1` / `case $cmd` as a dispatcher, not inner value cases.
    if "$1" not in subject and "cmd" not in subject.lower():
        return
    for item in parts[1:]:
        pattern = getattr(item, "word", None)
        if not pattern:
            continue
        name = pattern.strip(")").strip()
        if name in ("esac", "*", ""):
            continue
        ir.subcommands.append(SubCommand(name=name, help=humanize(name)))


def _extract_getopts(words, ir: ScriptIR) -> None:
    optstring = ""
    for w in words:
        text = getattr(w, "word", "").strip("'\"")
        if text.startswith(":"):
            optstring = text[1:]
            break
    for ch in optstring:
        if ch == ":":
            continue
        takes = optstring[optstring.find(ch) + 1: optstring.find(ch) + 2] == ":"
        ir.flags.append(
            FlagSpec(short=f"-{ch}", long=f"--{ch}", takes_value=takes, help=humanize(ch))
        )


# --------------------------------------------------------------------------- scanner fallback


READ_RE = re.compile(r"\bread\s+(?:-[a-zA-Z]*\s+)*(?:-p\s+)?([^\n;|)]*)")
CASE_LABEL_RE = re.compile(r"^\s*([a-z0-9_-]+|\*)\)\s*(.*)$")
GETOPTS_RE = re.compile(r"getopts\s+[\"':]*([a-zA-Z:]+)")
SELECT_RE = re.compile(r"^\s*select\s+(\w+)\s+in\s+(.+)$")
READ_P_RE = re.compile(r"read\s+(?:-[a-zA-Z]*p[a-zA-Z]*)\s+[\"']?([^\"']*)[\"']?")


def _scan_bash(lines: list[str], ir: ScriptIR) -> None:
    if len(lines) > MAX_PARSE_LINES:
        # Scan only the head/tail of a generated artefact.
        lines = lines[:500] + ["..."] + lines[-200:]
    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue

        # A `read` that consumes a herestring or a pipe is DATA PARSING,
        # not a human prompt: `read -r proto state recvq < /proc/net/tcp`.
        is_data_read = "<<<" in line or re.search(r"\|\s*\s*read\b", line) or "<" in line

        m_p = READ_P_RE.search(line)
        if m_p and re.search(r"\bread\b", line) and not is_data_read:
            q = m_p.group(1).strip()
            after = line[m_p.end():].strip()
            var = after.split()[0].lstrip("$") if after else "value"
            ir.prompt_sites.append(
                PromptSite(
                    line=idx,
                    prompt=q or humanize(var),
                    var=var,
                    widget=guess_widget(var, q),
                    choices=_choices_from_surround(lines, idx),
                )
            )
            continue

        if not is_data_read and (re.search(r"\bread\s+-", line) or re.search(r"\bread\s+[a-zA-Z_]", line)):
            m = READ_RE.search(line)
            if m:
                args = [a for a in m.group(1).split() if not a.startswith("-") and a.isidentifier()]
                # A prompt reads 1-3 values; more than that is parsing.
                for var in args[:2]:
                    ir.prompt_sites.append(
                        PromptSite(
                            line=idx,
                            prompt=humanize(var),
                            var=var,
                            widget=guess_widget(var),
                            choices=_choices_from_surround(lines, idx),
                        )
                    )
            continue

        m_sel = SELECT_RE.match(line)
        if m_sel:
            choices = [c.strip("'\" ") for c in m_sel.group(2).split()]
            ir.prompt_sites.append(
                PromptSite(
                    line=idx,
                    prompt=humanize(m_sel.group(1)),
                    var=m_sel.group(1),
                    widget=Widget.CHOICE,
                    choices=choices,
                )
            )
            continue

        m_g = GETOPTS_RE.search(line)
        if m_g:
            optstring = m_g.group(1)
            for ch in optstring:
                if ch == ":":
                    continue
                takes = optstring[optstring.find(ch) + 1: optstring.find(ch) + 2] == ":"
                ir.flags.append(
                    FlagSpec(short=f"-{ch}", long=f"--{ch}", takes_value=takes)
                )
            continue

        m_c = CASE_LABEL_RE.match(line)
        if m_c:
            name, inline_help = m_c.group(1), m_c.group(2).strip()
            if name not in ("*", "esac", ";;") and inline_help:
                ir.subcommands.append(SubCommand(name=name, help=humanize(name)))

    # usage() blocks document subcommands as `name   description`
    for name, helptext in _usage_subcommands(lines):
        ir.subcommands.append(SubCommand(name=name, help=helptext))
    ir.subcommands = _dedupe_subcommands(ir.subcommands)


def _usage_subcommands(lines: list[str]) -> list[tuple[str, str]]:
    """`usage()` blocks document modes as `name   description` under 'Commands:'.

    Handles both bare headers and the `echo "Commands:"` style that real
    scripts use, and `echo "  list   does a thing"` for the entries.
    """
    out: list[tuple[str, str]] = []
    inside = False
    for raw in lines[:80]:
        line = raw.rstrip()
        # strip an `echo "..."` / `printf ...` wrapper if present
        m_echo = re.match(r"""^\s*echo\s+(['"])(?P<body>.*)\1\s*$""", line)
        if m_echo:
            line = m_echo.group("body")
        m_prf = re.match(r"""^\s*printf\s+(['"])(?P<body>.*)\1\s*$""", line)
        if m_prf:
            line = m_prf.group("body")

        if re.match(r"^\s*(#\s*)?(Commands|Subcommands|Actions|Usage)\s*[:：]", line, re.I):
            inside = True
            continue
        if inside and re.match(r"^\s*(#\s*)?(Examples|Notes?|Options?|Environment|Flags?|Files?|License|See also)\s*[:：]", line, re.I):
            break  # a new section begins - what we collected is complete
        if inside:
            if not line.strip():
                if out:
                    break
                continue
            m = re.match(
                r"^\s{2,}([a-z][a-z0-9_-]{0,24}(?:\s*<[^>]*>)*)\s{1,}(\S.*?)\s*$", line
            )
            if m and len(m.group(2)) >= 2:
                out.append((m.group(1).split("<")[0].strip(), m.group(2).rstrip(" .")))
            elif out:
                break
    return out


def _choices_from_surround(lines: list[str], line: int) -> list[str]:
    """Look upward for a just-printed menu and reuse it as real choices.

    Only single-token menu entries are accepted (`1) sta  2) ap  3) mon`);
    prose after them is dropped so we never surface garbage as an option.
    """
    if not line:
        return []
    for back in range(line - 1, max(line - 6, 0), -1):
        prev = lines[back].strip()
        if not prev or prev.startswith("#"):
            continue
        inline = re.findall(r"(?:\(|^|[\s;])[1-9][\).]\s*([A-Za-z0-9_.-]{1,20})(?:\s|$|[,;])", prev)
        if len(inline) >= 2:
            return list(dict.fromkeys(inline))[:6]
        words = re.findall(r"[\"']([a-zA-Z][a-zA-Z0-9_-]{0,18})[\"']", prev)
        if len(words) >= 2:
            return list(dict.fromkeys(words))[:6]
    return []


# --------------------------------------------------------------------------- helpers


def _doc_comment(lines: list[str]) -> str:
    for line in lines[:12]:
        s = line.strip()
        if s.startswith("#!") and "python" not in s and "perl" not in s:
            continue
        if s.startswith("#") and len(s) > 2:
            body = s.lstrip("# ").strip()
            # skip decorative rules / banners
            if not body or set(body) <= set("═=-─━━*#·."):
                continue
            return body
    return ""


def _usage_from_heredoc(lines: list[str]) -> str:
    capture = False
    buf: list[str] = []
    for line in lines:
        if re.search(r"<<\s*['\"]?USAGE", line, re.I):
            capture = True
            continue
        if capture:
            if line.strip() in ("EOF", "USAGE") or re.match(r"^\s*\w+$", line.strip() or "x"):
                break
            buf.append(line.rstrip())
    return "\n".join(buf).strip()


def _detect_tools(text: str) -> list[str]:
    found = set()
    for tool in TOOL_SHAPES:
        if re.search(rf"(?<![\w-]){re.escape(tool)}(?![\w-])", text):
            found.add(tool)
    return sorted(found)


def _mark_fullscreen(ir: ScriptIR, detected: list[str]) -> None:
    if any(t in detected for t in ("htop", "vim", "top")):
        ir.warnings.append("launches a full-screen TUI")


def _classify(ir: ScriptIR) -> Kind:
    if ir.subcommands and not ir.prompt_sites:
        return Kind.PARAMETRIC
    if ir.prompt_sites:
        return Kind.INTERACTIVE
    if ir.positional_args or ir.flags:
        return Kind.PARAMETRIC
    if ir.detected_tools and any(t in FULLSCREEN_TOOLS for t in ir.detected_tools):
        return Kind.FULLSCREEN
    if ir.field_count() == 0 and ir.line_count <= 12:
        return Kind.SKELETAL
    if ir.field_count() == 0:
        return Kind.SKELETAL
    return Kind.PARAMETRIC


def _dedupe_prompts(sites: list[PromptSite]) -> list[PromptSite]:
    """One prompt per variable: a `read` inside a loop is still one question."""
    seen: set[str] = set()
    out: list[PromptSite] = []
    for site in sites:
        key = site.var.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(site)
    return out


def _dedupe_subcommands(subs: list[SubCommand]) -> list[SubCommand]:
    seen, out = set(), []
    for s in subs:
        if s.name in seen:
            continue
        seen.add(s.name)
        out.append(s)
    return out


def _dedupe_flags(flags: list[FlagSpec]) -> list[FlagSpec]:
    seen, out = set(), []
    for f in flags:
        if f.short in seen:
            continue
        seen.add(f.short)
        out.append(f)
    return out