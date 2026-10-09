"""Dispatch a script to the right language adapter and expose one entry point."""

from __future__ import annotations

from pathlib import Path

from .ir import Kind, Lang, ScriptIR
from .bash_adapter import analyze_bash, is_source_text
from .py_adapter import analyze_python
from .ps_adapter import analyze_batch, analyze_powershell

BASH_EXT = {".sh", ".bash", ".zsh", ".ksh", ""}
PY_EXT = {".py", ".py3"}
PS_EXT = {".ps1", ".psm1"}
BAT_EXT = {".bat", ".cmd"}


def detect_lang(path: Path) -> Lang:
    """Shebang wins over extension; extension is the fallback."""
    try:
        first = path.open(errors="replace").readline().strip()
    except OSError:
        return Lang.UNKNOWN

    if first.startswith("#!"):
        low = first.lower()
        if "python" in low:
            return Lang.PYTHON
        if any(s in low for s in ("bash", "/sh", "zsh", "ksh", "dash")):
            return Lang.BASH
    suffix = path.suffix.lower()
    if suffix in PY_EXT:
        return Lang.PYTHON
    if suffix in PS_EXT:
        return Lang.POWERSHELL
    if suffix in BAT_EXT:
        return Lang.BATCH
    if suffix in BASH_EXT:
        return Lang.BASH
    return Lang.UNKNOWN


def analyze(path: Path | str) -> ScriptIR:
    """Public entry point: analyze any script into the shared IR."""
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise FileNotFoundError(f"no such script: {p}")

    if not is_source_text(p):
        ir = ScriptIR(path=p, lang=Lang.UNKNOWN)
        ir.warnings.append("binary or oversized file - not a source script")
        ir.kind = Kind.UNKNOWN
        return ir

    lang = detect_lang(p)
    if lang is Lang.PYTHON:
        return analyze_python(p)
    if lang is Lang.BASH:
        return analyze_bash(p)
    if lang is Lang.POWERSHELL:
        return analyze_powershell(p)
    if lang is Lang.BATCH:
        return analyze_batch(p)

    ir = ScriptIR(path=p, lang=Lang.UNKNOWN)
    ir.warnings.append("unrecognised shebang/extension")
    return ir


def scan_directory(root: Path | str, recursive: bool = True) -> list[ScriptIR]:
    """Analyze every script under `root`. Symlinks are resolved, not followed."""
    base = Path(root).expanduser().resolve()
    pattern = "**/*" if recursive else "*"
    out: list[ScriptIR] = []
    seen_paths: set[Path] = set()
    for item in sorted(base.glob(pattern)):
        if not item.is_file():
            continue
        if item.name.startswith("."):
            continue
        try:
            real = item.resolve()
        except OSError:
            continue
        if real in seen_paths:  # symlinked duplicate
            continue
        seen_paths.add(real)
        lang = detect_lang(item)
        if lang is Lang.UNKNOWN:
            continue
        try:
            out.append(analyze(item))
        except Exception as exc:  # noqa: BLE001 - never let one bad file stop the scan
            ir = ScriptIR(path=item, lang=lang)
            ir.warnings.append(f"analysis failed: {type(exc).__name__}")
            out.append(ir)
    return out


__all__ = [
    "analyze",
    "detect_lang",
    "scan_directory",
    "Kind",
    "Lang",
    "ScriptIR",
]