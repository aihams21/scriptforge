"""scriptforge.core.parser package.

`classify.analyze()` is the public entry point. Both adapters emit the same
`ScriptIR`, so nothing downstream ever branches on language again.
"""

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
)
from .classify import analyze, detect_lang, scan_directory
from .ps_adapter import analyze_batch, analyze_powershell

__all__ = [
    "ArgSpec",
    "FlagSpec",
    "Kind",
    "Lang",
    "OutputHint",
    "OutputShape",
    "PromptSite",
    "ScriptIR",
    "SubCommand",
    "Widget",
    "analyze",
    "analyze_batch",
    "analyze_powershell",
    "detect_lang",
    "scan_directory",
]