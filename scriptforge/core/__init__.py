"""scriptforge.core package."""

from .parser.classify import analyze, detect_lang, scan_directory
from .parser.ir import Kind, Lang, ScriptIR

__all__ = ["analyze", "detect_lang", "scan_directory", "Kind", "Lang", "ScriptIR"]