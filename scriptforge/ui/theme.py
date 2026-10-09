"""Visual identity: colours + the AIHAM AM banner."""

from __future__ import annotations

VERSION = "0.1.0"
AUTHOR = "AIHAM AM"

BANNER = r"""
   ___  _____ ____ _   _  _____
  / __||  _  |_   _| | | ||  ___|   any script -> a real app
  \__ \ | |__  | | | |_| || |_      _   _    | |   ____ ___
  |___/ |____| |_|  \__, |___|     | |_| |   | |  / __|  _ \
                          |___/     \__, |   | | | (__| | | |
   _   _   ___  ____ _    _____      __/ |   |_|  \___|_| |_|
  | | | | / _ \|  _ \ |  |_   _|    /____|
  | |_| || | | | |_) || | | | |    scriptforge v{version}
  |  _  || |_| |  _ < | | | | |           {author}
  |_| |_| \___/|_| \_\|_| |_| |_|          {tagline}
"""

TAGLINE = "bash + python, one interface"

# Kali-ish palette: dragon blue / terminal green on dark.
BG = "#0d1117"
PANEL = "#161b22"
ACCENT = "#00d7af"
ACCENT2 = "#ff4d6d"
WARN = "#ffb800"
TEXT = "#c9d1d9"
DIM = "#6e7681"
OK = "#3fb950"
CRIT = "#f85149"


def banner(width: int = 0) -> str:
    return BANNER.format(version=VERSION, author=AUTHOR, tagline=TAGLINE)


def version_line() -> str:
    return f"scriptforge {VERSION} — by {AUTHOR}"


KIND_COLOR = {
    "interactive": ACCENT,
    "parametric": "#58a6ff",
    "skeletal": WARN,
    "fullscreen": ACCENT2,
    "opaque": DIM,
    "unknown": DIM,
}


def kind_color(kind: str) -> str:
    return KIND_COLOR.get(kind, TEXT)