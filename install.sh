#!/usr/bin/env bash
# One-line installer.
#
#   curl -fsSL https://raw.githubusercontent.com/aihams21/scriptforge/main/install.sh | bash
#
# Idempotent, non-interactive by default, and safe to re-run: it only installs
# what is missing and never removes anything.
set -euo pipefail

REPO="https://github.com/aihams21/scriptforge"
TAG="${SCRIPTFORGE_TAG:-v0.1.0}"
PREFIX="${SCRIPTFORGE_PREFIX:-$HOME/.local/share/scriptforge}"
APP_BIN="${SCRIPTFORGE_BIN:-$HOME/.local/bin}"
GUI_ONLY=0

GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RED=$'\033[31m'
CYAN=$'\033[36m'; DIM=$'\033[2m'; BOLD=$'\033[1m'; OFF=$'\033[0m'
[ -t 1 ] || { GREEN=""; YELLOW=""; RED=""; CYAN=""; DIM=""; BOLD=""; OFF=""; }

step() { printf '%s==>%s %s%s%s\n' "$CYAN" "$OFF" "$BOLD" "$1" "$OFF"; }
ok()   { printf '  %s✓%s %s\n' "$GREEN" "$OFF" "$1"; }
warn() { printf '  %s!%s %s\n' "$YELLOW" "$OFF" "$1"; }
die()  { printf '  %s✗%s %s\n' "$RED" "$OFF" "$1" >&2; exit 1; }

trap 'die "install failed at line $LINENO"' ERR

for arg in "$@"; do
  case "$arg" in
    --gui) GUI_ONLY=1 ;;
    --prefix=*) PREFIX="${arg#*=}" ;;
    --help|-h)
      sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
  esac
done

printf '\n%sScriptForge%s %s— any script becomes a usable app\n\n' "$BOLD" "$OFF" "$DIM"

# ---------------------------------------------------------------- system deps
# Debian/Ubuntu only. Kali and Ubuntu derivatives are the target; elsewhere we
# skip rather than guess at a package manager.
need_sudo=""
if [ "$(id -u)" -ne 0 ]; then
  if command -v sudo >/dev/null 2>&1; then
    need_sudo="sudo"
  fi
fi

if command -v apt-get >/dev/null 2>&1 && [ -z "$SKIP_APT" ]; then
  step "system packages"
  # Qt needs these at import time on a bare container. python3-pip/venv build the
  # virtualenv; the rest are Qt/xcb runtime libraries that are present on a
  # desktop but absent on a fresh VM.
  APT_PKGS="python3 python3-venv python3-pip libgl1 libegl1 libxkbcommon-x11-0 libdbus-1-3 libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libxcb-xkb1 libxkbcommon0 libfontconfig1"
  if command -v apt-get >/dev/null 2>&1; then
    MISSING=""
    for pkg in $APT_PKGS; do
      if ! dpkg -s "$pkg" >/dev/null 2>&1; then
        MISSING="$MISSING $pkg"
      fi
    done
    if [ -n "$MISSING" ]; then
      $need_sudo apt-get update -qq || warn "apt-get update failed, trying install anyway"
      # shellcheck disable=SC2086
      DEBIAN_FRONTEND=noninteractive $need_sudo apt-get install -y -qq $MISSING \
        || warn "some packages could not be installed; continuing"
      ok "system packages ready"
    else
      ok "system packages already present"
    fi
  fi
else
  step "system packages"
  warn "apt-get not found; assuming dependencies are present"
fi

# ------------------------------------------------------------------- fetch
step "download"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

if [ -n "$SCRIPTFORGE_LOCAL" ]; then
  SRC="$SCRIPTFORGE_LOCAL"
  ok "using local source: $SRC"
else
  URL="$REPO/archive/refs/tags/$TAG.tar.gz"
  if ! curl -fsSL "$URL" -o "$TMP/sf.tar.gz"; then
    URL="$REPO/archive/refs/heads/main.tar.gz"
    curl -fsSL "$URL" -o "$TMP/sf.tar.gz" || die "download failed: $URL"
  fi
  tar -xzf "$TMP/sf.tar.gz" -C "$TMP"
  SRC="$(find "$TMP" -maxdepth 1 -type d -name 'scriptforge-*' | head -1)"
  [ -n "$SRC" ] || die "unexpected archive layout"
  ok "downloaded $TAG"
fi

mkdir -p "$PREFIX" "$APP_BIN"
cp -r "$SRC/scriptforge" "$PREFIX/scriptforge"
cp -r "$SRC/packaging" "$PREFIX/packaging"
# pyproject.toml must sit beside the package directory: the project root is what
# pip installs from, so shipping only scriptforge/ yields "not a Python project".
[ -f "$SRC/pyproject.toml" ] && cp "$SRC/pyproject.toml" "$PREFIX/pyproject.toml"
[ -f "$SRC/LICENSE" ] && cp "$SRC/LICENSE" "$PREFIX/LICENSE"
[ -f "$SRC/README.md" ] && cp "$SRC/README.md" "$PREFIX/README.md"
rm -rf "$PREFIX/scriptforge/__pycache__" "$PREFIX/scriptforge/gui/__pycache__"
ok "installed to $PREFIX"

# ------------------------------------------------------------- virtualenv
step "python environment"
if [ ! -x "$PREFIX/venv/bin/python" ]; then
  python3 -m venv "$PREFIX/venv" || die "could not create a virtualenv (install python3-venv)"
fi
"$PREFIX/venv/bin/python" -m pip install -q --upgrade pip setuptools wheel >/dev/null 2>&1 || true
"$PREFIX/venv/bin/python" -m pip install -q -e "$PREFIX" || die "could not install scriptforge"
if [ "$GUI_ONLY" -eq 1 ]; then
  "$PREFIX/venv/bin/python" -m pip install -q PySide6 || die "could not install PySide6"
fi
ok "venv ready at $PREFIX/venv"

ln -sf "$PREFIX/venv/bin/scriptforge" "$APP_BIN/scriptforge"
case ":$PATH:" in
  *":$APP_BIN:"*) ;;
  *) warn "$APP_BIN is not on your PATH — add it to open a terminal" ;;
esac
ok "linked $APP_BIN/scriptforge"

# ------------------------------------------------------------------- launch
if [ "$GUI_ONLY" -eq 1 ] && [ -n "$DISPLAY$WAYLAND_DISPLAY" ]; then
  step "desktop integration"
  "$PREFIX/packaging/linux/install-desktop.sh" >/dev/null 2>&1 \
    && ok "desktop icon installed" \
    || warn "could not install the desktop icon (no permissions?)"
fi

# --------------------------------------------------------------------- self test
step "self-test"
PY="$PREFIX/venv/bin/python"
"$PY" - "$PREFIX" <<'PYCHECK'
import sys, pathlib
root = pathlib.Path(sys.argv[1])
sys.path.insert(0, str(root))

from scriptforge.core.parser.classify import analyze
from scriptforge.core.rewriter import rewrite

probe = root / "_selftest.sh"
probe.write_text('#!/bin/bash\necho "host:"\nread -r h\necho "ok $h"\n')
ir = analyze(probe)
assert ir.prompt_sites, "parser recovered no prompts"
assert ir.kind.value == "interactive", ir.kind
before = probe.read_bytes()
res = rewrite(ir)
assert res.ok, res.message
assert probe.read_bytes() == before, "rewrite touched the original"
probe.unlink()

try:
    import PySide6  # noqa: F401
    have_gui = True
except Exception:
    have_gui = False
print(f"  parser  ok  {len(ir.prompt_sites)} prompt(s) recovered")
print(f"  rewriter ok  wrapper built, source untouched")
print(f"  gui     {'ok  PySide6 present' if have_gui else 'absent  (run with --gui)'}")
PYCHECK
ok "self-test passed"

printf '\n%sScriptForge is ready.%s\n\n' "$GREEN" "$OFF"
printf '  window   %s gui\n' "$APP_BIN/scriptforge"
printf '  terminal %s\n' "$APP_BIN/scriptforge tui"
printf '  inspect  %s inspect ~/bin/yourscript.sh\n\n' "$APP_BIN/scriptforge"