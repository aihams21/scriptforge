#!/usr/bin/env bash
# scriptforge installer - by AIHAM AM
# Creates a venv, installs dependencies, verifies the install, and prints
# follow-up commands. Safe to re-run.

set -euo pipefail

# flags: --desktop   also install the icon + app-menu + Desktop entry
#        --desktop-only   skip the venv work, just do the desktop integration
WANT_DESKTOP=0
DESKTOP_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --desktop)       WANT_DESKTOP=1 ;;
    --desktop-only)  WANT_DESKTOP=1; DESKTOP_ONLY=1 ;;
    *) printf "unknown flag: %s\n" "$arg" >&2; exit 2 ;;
  esac
done

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$HERE/.venv"
GREEN=$'\033[32m'; RED=$'\033[31m'; DIM=$'\033[2m'; CYAN=$'\033[36m'; OFF=$'\033[0m'

step() { printf '%s==>%s %s\n' "$CYAN" "$OFF" "$1"; }
ok()   { printf '  %s✓%s %s\n' "$GREEN" "$OFF" "$1"; }
die()  { printf '  %s✗%s %s\n' "$RED" "$OFF" "$1" >&2; exit 1; }

printf '%s' "$GREEN"
cat <<'BANNER'
   ___  _____ ____ _   _  _____
  / __||  _  |_   _| | | ||  ___|   any script -> a real app
  |__ \ | |__  | | | |_| || |_      _   _    | |   ____ ___
  |___/ |____| |_|  \__, |___|     | |_| |   | |  / __|  _ \
                          |___/     \__, |   | | | (__| | | |
   _   _   ___  ____ _    _____      __/ |   |_|  \___|_| |_|
  | | | | / _ \|  _ \ |  |_   _|    /____|
  | |_| || | | | |_) || | | | |    scriptforge
  |  _  || |_| |  _ < | | | | |           AIHAM AM
  |_| |_| \___/|_| \_\|_| |_| |_|          bash + python, one interface
BANNER
printf '%s' "$OFF"

if [ "$DESKTOP_ONLY" -eq 1 ]; then
  SCRIPTFORGE_EXEC="$VENV/bin/scriptforge" \
    "$HERE/packaging/linux/install-desktop.sh"
  exit 0
fi

# ---------------------------------------------------------------- preflight

step "Checking prerequisites"

command -v python3 >/dev/null || die "python3 not found - install python3 first"

PYV="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
ok "python3 $PYV"
python3 - <<'PY' || die "python 3.10+ required (found $(python3 -V 2>&1))"
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
ok "version check passed"

# ---------------------------------------------------------------- venv

if [ ! -d "$VENV" ]; then
  step "Creating virtual environment"
  python3 -m venv "$VENV" || die "could not create venv at $VENV"
  ok "created $VENV"
else
  ok "reusing existing $VENV"
fi

PY="$VENV/bin/python"
[ -x "$PY" ] || die "missing interpreter at $PY"

step "Upgrading pip"
"$PY" -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true
ok "pip ready"

# ---------------------------------------------------------------- deps

step "Installing dependencies"
if ! "$PY" -m pip install --quiet -e "$HERE" 2>/dev/null; then
  printf '  %s!%s editable install failed, trying plain dependencies\n' "$DIM" "$OFF"
  "$PY" -m pip install --quiet \
    "bashlex>=0.18" "textual>=0.60" "pexpect>=4.9" \
    || die "dependency install failed - check your network"
fi
ok "bashlex, textual, pexpect installed"

# ---------------------------------------------------------------- verify

step "Verifying the install"

cd "$HERE"
export PYTHONPATH="$HERE"

"$PY" - <<'PY' || die "self-test failed - the install is not usable"
import tempfile
from pathlib import Path

from scriptforge.core.parser import Kind, analyze
from scriptforge.core.rewriter import rewrite
from scriptforge.core.runner import HAS_PEXPECT, ScriptRunner
from scriptforge.forge import plan
from scriptforge.ui import theme

tmp = Path(tempfile.mkdtemp())

# 1. an interactive bash script must recover its prompts
ask = tmp / "ask.sh"
ask.write_text('#!/bin/bash\necho "target:"\nread -r target\necho "hit $target"\n')
ask.chmod(0o755)
ir = analyze(ask)
assert ir.kind is Kind.INTERACTIVE, ir.kind
assert [s.var for s in ir.prompt_sites] == ["target"], ir.prompt_sites
print("  parser   ok   recovered 1 prompt from a bash script")

# 2. a UI-less script must be planned for re-programming
wrapper = tmp / "acct"
wrapper.write_text('#!/bin/bash\nsomecli --config /x/settings "$@"\n')
wrapper.chmod(0o755)
p = plan(wrapper)
assert p.action == "rewrite", p.action
res = rewrite(p.ir, out_dir=tmp / "built", force=True)
assert res.ok, res.message
assert wrapper.read_text() == '#!/bin/bash\nsomecli --config /x/settings "$@"\n', "source was modified!"
print("  rewriter ok   generated a wrapper, original untouched")

# 3. the runner must execute a script and capture its output
r = ScriptRunner(ask, answers={"target": "10.0.0.1"}, timeout=30).run_interactive()
assert "hit 10.0.0.1" in r.output, r.output
print(f"  runner   ok   pty={'yes' if HAS_PEXPECT else 'no'}, exit={r.exit_code}")

# 4. the UI must import and report its version
print(f"  ui       ok   {theme.version_line()}")
PY
ok "self-test passed"

# ---------------------------------------------------------------- done

cat <<DONE

$(printf '%s' "$GREEN")scriptforge is ready.$(printf '%s' "$OFF")

  Run it:            $VENV/bin/scriptforge
  Alias for now:     alias scriptforge='$VENV/bin/scriptforge'

  Try:
    $VENV/bin/scriptforge                       interactive UI
    $VENV/bin/scriptforge scan ~/bin           classify your scripts
    $VENV/bin/scriptforge inspect ~/bin/<one>  show a recovered interface

  Add the icon to your Desktop and app menu:
    ./install.sh --desktop

DONE