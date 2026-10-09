"""Python -> ScriptIR adapter using the stdlib `ast` module.

Recovers the interface of a python script from `argparse`, `input()`, and
`getpass` without executing it. Falls back to a line scanner on syntax errors.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from .ir import (
    ArgSpec,
    FlagSpec,
    Kind,
    Lang,
    OutputHint,
    OutputShape,
    PromptSite,
    ScriptIR,
    SubCommand,
    Widget,
    guess_widget,
    humanize,
)

from .bash_adapter import TOOL_SHAPES, FULLSCREEN_TOOLS, _choices_from_surround


def analyze_python(path: Path) -> ScriptIR:
    text = path.read_text(errors="replace")
    lines = text.splitlines()
    ir = ScriptIR(path=path, lang=Lang.PYTHON, line_count=len(lines))
    ir.shebang = lines[0].strip() if lines and lines[0].startswith("#!") else ""
    ir.description = _py_docstring(lines)

    try:
        tree = ast.parse(text)
        ir.parse_mode = "ast"
    except SyntaxError as exc:
        ir.warnings.append(f"syntax error line {exc.lineno}; used line scanner")
        _scan_py(lines, ir)
        ir.parse_mode = "scan"
        _finalize(ir)
        return ir

    ir.imports = _collect_imports(tree)
    ir.detected_tools = _detect_tools(text)
    ir.output_hints = [
        OutputHint(tool=t, shape=TOOL_SHAPES.get(t, OutputShape.TEXT), reason="known tool")
        for t in ir.detected_tools
    ]

    _walk(tree, ir, lines)
    _finalize(ir)
    return ir


def _collect_imports(tree) -> list[str]:
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                mods.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                mods.add(node.module.split(".")[0])
    return sorted(mods)


def _walk(node, ir: ScriptIR, lines: list[str]) -> None:
    """Every node is visited, so `input()` inside `def main()` is found too."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.Call):
            _maybe_argparse(child, ir)
            _maybe_input(child, ir, lines)
        elif isinstance(child, ast.Assign) and _is_argv(child):
            _from_argv(child, ir)
        _walk(child, ir, lines)


def _maybe_argparse(call, ir: ScriptIR) -> None:
    """Pull add_argument() calls off a parser object."""
    func = call.func
    if not isinstance(func, ast.Attribute) or func.attr != "add_argument":
        return
    positional: list[ast.expr] = []
    optional = False
    help_text = ""
    for kw in call.keywords:
        if kw.arg == "help" and isinstance(kw.value, ast.Constant):
            help_text = str(kw.value.value)
        if kw.arg == "nargs":
            if isinstance(kw.value, ast.Constant) and kw.value.value == "?":
                optional = True
    for arg in call.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            positional.append(arg)

    if not positional:
        return
    raw = str(positional[0].value)
    is_flag = raw.startswith("-")
    name = raw.lstrip("-")

    if is_flag:
        long_form = next(
            (str(a.value) for a in positional[1:] if str(a.value).startswith("--")),
            None,
        )
        takes_value = not any(kw.arg in ("action", "store_true", "store_false") for kw in call.keywords)
        if "action" in {kw.arg for kw in call.keywords}:
            takes_value = False
        ir.flags.append(
            FlagSpec(
                short=raw if len(raw) == 2 else raw[:2],
                long=long_form or raw,
                takes_value=takes_value,
                help=help_text,
            )
        )
    else:
        ir.positional_args.append(ArgSpec(index=len(ir.positional_args), name=name, help=help_text))


def _maybe_input(call, ir: ScriptIR, lines: list[str]) -> None:
    func = call.func
    fname = getattr(func, "id", None) or getattr(func, "attr", None)
    if fname not in ("input", "raw_input", "getpass"):
        return
    prompt = ""
    if call.args and isinstance(call.args[0], ast.Constant):
        prompt = str(call.args[0].value)
    elif call.args:
        prompt = "value"
    widget = Widget.SECRET if fname == "getpass" else guess_widget(prompt, prompt)
    ir.prompt_sites.append(
        PromptSite(
            line=getattr(call, "lineno", 0),
            prompt=prompt or humanize("value"),
            var=prompt or "value",
            widget=widget,
            choices=_choices_from_surround(lines, getattr(call, "lineno", 0)),
        )
    )


def _is_argv(node: ast.Assign) -> bool:
    targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
    return any(t in ("argv", "args") for t in targets)


def _from_argv(node: ast.Assign, ir: ScriptIR) -> None:
    """`args = sys.argv[1:]` -> positional args come from the command line."""
    if not ir.positional_args:
        ir.warnings.append("reads sys.argv directly (no argparse); positional args inferred")


INPUT_RE = re.compile(r"\b(?:input|raw_input|getpass)\s*\(")
ARGP_RE = re.compile(r"add_argument\(\s*[\"']([^\"']+)[\"']")


def _scan_py(lines: list[str], ir: ScriptIR) -> None:
    for idx, line in enumerate(lines, start=1):
        if INPUT_RE.search(line):
            m = re.search(r"input\(\s*f?[\"']([^\"']+)", line)
            prompt = m.group(1) if m else humanize("value")
            ir.prompt_sites.append(
                PromptSite(
                    line=idx,
                    prompt=prompt,
                    var=prompt,
                    widget=guess_widget(prompt, prompt),
                    choices=_choices_from_surround(lines, idx),
                )
            )
        m2 = ARGP_RE.search(line)
        if m2:
            name = m2.group(1)
            if name.startswith("-"):
                ir.flags.append(FlagSpec(short=name[:2], long=name, help=""))
            else:
                ir.positional_args.append(ArgSpec(index=len(ir.positional_args), name=name))


def _py_docstring(lines: list[str]) -> str:
    for lineno, line in enumerate(lines[:15]):
        s = line.strip()
        if lineno == 0 and s.startswith("#!"):
            continue  # the shebang is not a docstring
        if s.startswith(('"""', "'''")):
            return s.strip("\"'").strip()
        if s.startswith("#") and len(s) > 2:
            body = s.lstrip("# ").strip()
            if body and not set(body) <= set("═=-─━*#·."):
                return body
    return ""


def _detect_tools(text: str) -> list[str]:
    found = set()
    for tool in TOOL_SHAPES:
        if re.search(rf"(?<![\w-]){re.escape(tool)}(?![\w-])", text):
            found.add(tool)
    return sorted(found)


SHIM_RE = re.compile(r"^\s*(from\s+\S+\s+import\s+\w+|import\s+\S+|sys\.exit\()", re.M)


def _is_entry_point_shim(lines: list[str]) -> bool:
    """`<pkg>` console scripts are just `sys.exit(main())` - no UI to recover."""
    body = [l for l in lines if l.strip() and not l.strip().startswith("#!")]
    if len(body) > 6:
        return False
    joined = "\n".join(body)
    if not SHIM_RE.search(joined):
        return False
    return "main()" in joined or "console_scripts" in joined


def _finalize(ir: ScriptIR) -> None:
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

    if ir.detected_tools and any(t in FULLSCREEN_TOOLS for t in ir.detected_tools):
        ir.kind = Kind.FULLSCREEN
    elif ir.subcommands and not ir.prompt_sites:
        ir.kind = Kind.PARAMETRIC
    elif ir.prompt_sites:
        ir.kind = Kind.INTERACTIVE
    elif ir.positional_args or ir.flags:
        ir.kind = Kind.PARAMETRIC
    elif _is_entry_point_shim(ir.path.read_text(errors="replace").splitlines()):
        ir.kind = Kind.OPAQUE
        ir.warnings.append("console-script shim (delegates to a package); no own interface")
    else:
        ir.kind = Kind.SKELETAL