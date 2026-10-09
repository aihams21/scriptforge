#!/usr/bin/env bash
# Codespaces bootstrap. Deliberately mirrors install.sh so the cloud workspace
# and a bare metal box end up with byte-identical tooling.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

python3 -m venv .venv
.venv/bin/python -m pip install --quiet --upgrade pip setuptools wheel
.venv/bin/python -m pip install --quiet -e ".[gui,dev]"

# Qt needs these even though the container has no GPU; without them PySide6
# imports fine and then aborts on the first window.
apt-get update -qq
apt-get install -y -qq libgl1 libegl1 libxkbcommon-x11-0 libdbus-1-3 \
  libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libxcb-xkb1 \
  libfontconfig1 xvfb >/dev/null

cat <<'MSG'

  ScriptForge ready.

    open the window   code . && code --reuse-window .  -> run "gui"
    run headless       xvfb-run -a .venv/bin/python -m scriptforge.cli gui
    tests              .venv/bin/python -m pytest tests/ -q

MSG
