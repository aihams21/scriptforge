"""scriptforge command line."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .core.parser import Kind, analyze, scan_directory
from .forge import execute, forge, plan
from .ui import theme

try:
    import typer

    HAS_TYPER = True
except Exception:  # pragma: no cover
    HAS_TYPER = False


def _print_usage() -> None:
    print(theme.banner())
    print(f"""
  {theme.version_line()}

USAGE
  scriptforge                    launch the desktop window (default)
  scriptforge gui [--lang ar]    same, with an explicit language
  scriptforge tui                terminal interface
  scriptforge inspect <script>   show the recovered interface
  scriptforge plan <script>      show what forging would do
  scriptforge forge <script>     re-program a UI-less script
  scriptforge run <script> [--answers K=V]...
  scriptforge scan <dir>         classify every script in a directory
  scriptforge history            recent runs
  scriptforge --version
""")


def _inspected(ir) -> None:
    print(f"\n\033[1m{ir.name}\033[0m  \033[2m{ir.path}\033[0m")
    print(f"  kind      \033[1m{ir.kind.value}\033[0m   lang {ir.lang.value}   parser {ir.parse_mode}")
    print(f"  lines     {ir.line_count}")
    if ir.description:
        print(f"  about     {ir.description}")
    if ir.detected_tools:
        print(f"  tools     {', '.join(ir.detected_tools)}")
    if ir.subcommands:
        print(f"  modes     {', '.join(s.name for s in ir.subcommands)}")
    if ir.positional_args:
        print(f"  args      {', '.join(a.name for a in ir.positional_args)}")
    if ir.flags:
        print(f"  flags     {', '.join(f.short for f in ir.flags)}")
    if ir.prompt_sites:
        print("\n  PROMPTS")
        for p in ir.prompt_sites[:25]:
            choices = f"  [{', '.join(p.choices[:4])}]" if p.choices else ""
            print(f"    L{p.line:<5} {p.prompt}  ({p.widget.value}){choices}")
        if len(ir.prompt_sites) > 25:
            print(f"    … +{len(ir.prompt_sites) - 25} more")
    if ir.warnings:
        print()
        for w in ir.warnings:
            print(f"  \033[33m⚠ {w}\033[0m")
    print()


def _parse_kv(items: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in items:
        if "=" in item:
            k, v = item.split("=", 1)
            out[k.strip()] = v
    return out


def _launch_desktop(rest: list[str]) -> int:
    """Start the Qt window.

    The default command is the desktop app, so a double-click on the icon lands
    on the GUI. A missing Qt is reported as an install instruction rather than a
    traceback, because that is what a launcher without a TTY actually shows the
    user.
    """

    lang = "en"
    roots: list[Path] = []
    for arg in rest:
        if arg.startswith("--lang="):
            lang = arg.split("=", 1)[1]
        elif arg in ("--lang", "--language"):
            continue
        elif not arg.startswith("-"):
            roots.append(Path(arg))
    if rest and rest[0] in ("--lang", "--language"):
        idx = rest.index(rest[0])
        if idx + 1 < len(rest):
            lang = rest[idx + 1]

    try:
        from .gui.main_window import run as run_desktop
    except ImportError as exc:
        print(
            "  The desktop window needs PySide6, which is not installed.\n\n"
            "    Linux    pip install PySide6\n"
            "    Windows  py -m pip install PySide6\n\n"
            f"  (import failed: {exc})",
            file=sys.stderr,
        )
        return 2
    return run_desktop([str(r) for r in roots] + ["--lang", lang])


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])

    if not argv:
        return _launch_desktop([])

    if argv[0] in ("-h", "--help", "help"):
        _print_usage()
        return 0

    if argv[0] in ("-v", "--version", "version"):
        print(theme.version_line())
        return 0

    cmd, rest = argv[0], argv[1:]

    if cmd in ("ui", "tui", "term"):
        from .ui.app import ScriptForge

        roots = [Path(a) for a in rest if not a.startswith("-")] or None
        ScriptForge(roots=roots).run()
        return 0

    if cmd in ("gui", "app", "desktop"):
        return _launch_desktop(rest)

    if cmd == "inspect":
        if not rest:
            print("usage: scriptforge inspect <script> [--json]", file=sys.stderr)
            return 2
        ir = analyze(rest[0])
        if "--json" in rest:
            print(json.dumps(ir.to_dict(), indent=2, ensure_ascii=False))
        else:
            _inspected(ir)
        return 0

    if cmd == "plan":
        if not rest:
            print("usage: scriptforge plan <script>", file=sys.stderr)
            return 2
        p = plan(rest[0])
        print(f"{p.title}\n  reason: {p.reason}")
        if p.fields:
            print(f"  fields: {', '.join(p.fields)}")
        return 0

    if cmd == "forge":
        if not rest:
            print("usage: scriptforge forge <script> [--force]", file=sys.stderr)
            return 2
        result = forge(rest[0], force="--force" in rest)
        print(result.message)
        if result.ok:
            print(f"  path: {result.generated}")
        return 0 if result.ok else 1

    if cmd == "run":
        if not rest:
            print("usage: scriptforge run <script> [--answers k=v ...] [-- k1 k2]", file=sys.stderr)
            return 2
        script = rest[0]
        answers: dict[str, str] = {}
        extra: list[str] = []
        i = 1
        while i < len(rest):
            if rest[i] == "--answers":
                j = i + 1
                while j < len(rest) and "=" in rest[j]:
                    answers.update(_parse_kv([rest[j]]))
                    j += 1
                i = j
            elif rest[i] == "--":
                extra = rest[i + 1:]
                break
            else:
                extra.append(rest[i])
                i += 1
        result = execute(script, answers=answers, args=extra)
        sys.stdout.write(result.output)
        return result.exit_code

    if cmd == "scan":
        root = rest[0] if rest else str(Path.home() / "bin")
        irs = scan_directory(root)
        counts: dict[str, int] = {}
        for ir in irs:
            counts[ir.kind.value] = counts.get(ir.kind.value, 0) + 1
        print(f"{len(irs)} scripts in {root}")
        for k, v in sorted(counts.items()):
            print(f"  {k:12} {v}")
        if "--verbose" in rest or "-v" in rest:
            print()
            for ir in irs:
                print(f"  {ir.kind.value:12} {ir.lang.value:7} {ir.name}")
        return 0

    if cmd == "history":
        from .core.vault import Vault

        limit = 20
        if rest:
            limit = int(rest[0])
        with Vault() as vault:
            rows = vault.recent_runs(limit)
            if not rows:
                print("no runs recorded yet")
                return 0
            for r in rows:
                mark = "✓" if r.exit_code == 0 else "✗"
                print(f"  {mark} {r.created_at:.0f}  {r.script_name:24} exit={r.exit_code:<4} {r.duration_s:.1f}s")
        return 0

    print(f"unknown command: {cmd}", file=sys.stderr)
    _print_usage()
    return 2


if __name__ == "__main__":
    sys.exit(main())