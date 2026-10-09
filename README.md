# ScriptForge

**أي سكربت ← تطبيق بإيدك.**

<div align="center">

![ScriptForge](packaging/icon/scriptforge-256.png)

**ScriptForge** — read any bash / python / PowerShell script, understand the
interface hiding inside it, and build a screen you can actually navigate.
If the script has **no interface at all**, ScriptForge re-programs it and
gives it one.

Runs *inside* your Linux distro — Kali bare-metal **or** Kali in VirtualBox.
Same package, same command, same look.

</div>

```
   ___  _____ ____ _   _  _____
  / __||  _  |_   _| | | ||  ___|   any script -> a real app
  \__ \ | |__  | | | |_| || |_      _   _    | |   ____ ___
  |___/ |____| |_|  \__, |___|     | |_| |   | |  / __|  _ \
                          |___/     \__, |   | | | (__| | | |
   _   _   ___  ____ _    _____      __/ |   |_|  \___|_| |_|
  | | | | / _ \|  _ \ |  |_   _|    /____/
  | |_| || | | | |_) || | | | |    scriptforge v0.1.0
  |  _  || |_| |  _ < | | | | |           by AIHAM AM
  |_| |_| \___/|_| \_\|_| |_| |_|          bash + python + powershell
```

---

## Table of contents

- [What it does](#what-it-does)
- [Install — Kali Linux / any Linux](#install--kali-linux--any-linux)
- [Install — Windows 10 / 11](#install--windows-10--11)
- [Usage](#usage)
- [How it works](#how-it-works)
- [Re-programming, with a real example](#re-programming-with-a-real-example)
- [Honest limitations](#honest-limits)
- [Development](#development)
- [License](#license)

---

## What it does

Pick a file. ScriptForge works out its shape and builds the right screen:

| Detected kind | What triggers it | What you get |
|---|---|---|
| `interactive` | `read`, `select`, `input()`, `Read-Host`, `set /p` | a **form**, one widget per question; answers are injected live over a PTY |
| `parametric` | `case $1`, `argparse`, `usage()` blocks, `param()`, `%1..%9` | a **menu** of modes + a field per argument |
| `skeletal` | no interface at all (usually a 3-line wrapper) | **re-programmed** into an interactive wrapper |
| `fullscreen` | curses apps (`htop`, `vim`) | the raw terminal, embedded |
| `opaque` | package console-scripts that delegate elsewhere | launched with free-form args |

Two extras:

- **History** — every run is recorded (command, answers, exit code, duration).
- **Non-destructive** — your original scripts are *never* modified. Generated
  wrappers go to `~/.scriptforge/built/`.

---

## Install — Kali Linux / any Linux

### Requirements

| | |
|---|---|
| OS | Linux (Kali recommended) |
| Python | **3.10+** |
| Network | only for the first install; after that it works fully offline |

### One command

```bash
git clone https://github.com/aihams21/scriptforge.git
cd scriptforge
chmod +x install.sh
./install.sh
```

The installer creates a private virtualenv, installs the dependencies,
**runs a self-test**, and prints the exact command to launch.

### Add the icon (Desktop + application menu)

```bash
./install.sh --desktop
```

That installs:

- the icon at all 8 standard sizes (`16` … `512`) plus a scalable SVG
- an application-menu entry named **ScriptForge**
- a launcher on your **Desktop**, pre-marked as trusted

Remove it again:

```bash
./packaging/linux/install-desktop.sh --uninstall
```

### Launch

```bash
scriptforge                        # if it is on your PATH
./.venv/bin/scriptforge            # straight from the folder
```

> **Note on Kali's PEP 668.** Kali marks Python as externally managed, so a bare
> `pip install` may refuse. `install.sh` uses a venv, which sidesteps it entirely.

### Manual install

```bash
cd scriptforge
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
scriptforge
```

---

## Install — Windows 10 / 11

Windows users get a native build that drives **PowerShell** (`.ps1`),
**batch** (`.bat` / `.cmd`) and **Python** scripts.

### One command

Open **PowerShell** in the scriptforge folder and run:

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```

That creates a venv, installs the dependencies, runs a self-test, and creates
shortcuts:

- **Start menu** → *ScriptForge*
- **Desktop** → *ScriptForge*

Both carry the ScriptForge icon.

If PowerShell's execution policy blocks the script, either use the flag above
or relax it once:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

### Uninstall

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1 -Uninstall
```

### Notes specific to Windows

- **No PTY.** `pexpect` is POSIX-only, so on Windows ScriptForge uses ordinary
  pipes. Streaming and history work; live prompt-injection of unmarked
  `Read-Host` prompts is not available.
- **Execution policy.** Generated wrappers are launched with
  `-ExecutionPolicy Bypass`, so they run even under a restrictive policy.
- **Kali tooling.** Windows has no Kali toolset. If you use Kali through
  VirtualBox or WSL, run ScriptForge *inside* Kali using the Linux install
  above — that path also gets the PTY features.

---

## Usage

```bash
scriptforge                            # the interactive TUI
scriptforge ui ~/bin ~/usr/local/bin    # start on specific folders

scriptforge inspect <script>            # what interface was recovered?
scriptforge inspect <script> --json     # same, as JSON
scriptforge plan <script>               # what would forging do?
scriptforge forge <script> --force      # re-program a UI-less script
scriptforge run <script> -- list        # run it, passing arguments
scriptforge scan ~/bin                  # classify every script in a folder
scriptforge history                     # recent runs
scriptforge --version                   # scriptforge 0.1.0 — by AIHAM AM
```

### Keys inside the TUI

| Key | Action |
|---|---|
| `↑` `↓` | move between scripts (the right pane updates live) |
| `/` | search |
| `Enter` | open the generated interface, or run it |
| `r` | rescan |
| `q` | quit |

---

## How it works

```
   bash script   ─┐
   python script ─┼─►  PARSER  ─►  IR  ─►  REWRITER  ─►  UI      ─►  RUNNER
   powershell   ──┤   bashlex        shared   generated    widgets      pipes
   batch        ─┘   ast / regex    model    wrapper                   (PTY on POSIX)
```

The **IR** (Intermediate Representation) is the key idea: every language
adapter emits the same structure, so nothing downstream ever branches on
language again.

```
scriptforge/
├── scriptforge/
│   ├── core/
│   │   ├── parser/
│   │   │   ├── ir.py             ★ the shared IR
│   │   │   ├── bash_adapter.py   bashlex, with a line-scanner fallback
│   │   │   ├── py_adapter.py     stdlib ast,  with a scanner fallback
│   │   │   ├── ps_adapter.py     PowerShell param() / Read-Host
│   │   │   └── classify.py       one entry point
│   │   ├── rewriter.py           ★ re-programming
│   │   ├── runner.py             process + PTY driving
│   │   └── vault.py              run history (SQLite)
│   ├── ui/
│   │   ├── app.py                main browser
│   │   ├── widgets.py            generated forms + the run console
│   │   └── theme.py              colours and the AIHAM AM banner
│   ├── forge.py                  ★ orchestrator
│   └── cli.py
├── packaging/
│   ├── icon/                     SVG source + all PNG sizes + .ico
│   ├── linux/                    .desktop template + icon installer
│   └── windows/                  Windows launcher bits
├── install.sh                    Linux installer
├── install.ps1                   Windows installer
├── scriptforge.bat               Windows launcher
└── tests/                        52 tests
```

---

## Re-programming, with a real example

A real script — `~/bin/cline-acct1`:

```bash
#!/usr/bin/env bash
cline --config /home/aiham/.cline-accounts/acct1/settings \
      --data-dir /home/aiham/.cline-accounts/acct1/data "$@"
```

No interface. `scriptforge forge cline-acct1` produces:

```
~/.scriptforge/built/cline-acct1     ← generated
~/bin/cline-acct1                    ← original, byte-for-byte untouched
```

The generated wrapper resolves the fixed argv, then offers a menu: run as-is,
add a value, or quit — and it exits cleanly on EOF instead of spinning.

---

## Honest limits

Things this will not do, stated plainly:

- **It is a static analyser.** There is no LLM. Interface recovery is AST plus
  pattern matching, so a prompt written in unusual prose may be labelled from
  its variable name instead (`ifc` → "Ifc"). You can always correct it before
  running.
- **Choice extraction is best-effort.** Numbered menus like
  `1) sta  2) ap  3) mon` are recovered well. Long Arabic menu text or menus
  printed from an array usually fall back to a free-text field.
- **A `read` with no prompt is still answerable**, but only because the runner
  treats *output going quiet* as "waiting for input". That works for scripts;
  for a program that simply pauses for two seconds, the timing heuristic could
  misfire.
- **Generated artefacts are skipped.** Anything over 5000 lines is treated as a
  bundle rather than a human script — a 3.5M-line bundled binary is not a
  script, and parsing it would hang.
- **Curses apps cannot be decomposed into widgets.** `htop` and `vim` get an
  embedded terminal, not a form. That is a hard limit of the terminal itself.
- **Windows has no PTY**, so prompt injection is unavailable there.

---

## Development

```bash
source .venv/bin/activate
pytest tests/ -q                 # 52 tests
python tests/test_tui_smoke.py   # headless UI check
```

The tests never touch your real `~/bin` — everything runs in `tmp_path`. Two
tests deliberately execute real generated scripts to cover the long path.

Regenerating the icons after editing the SVG:

```bash
cd packaging/icon
python3 -c "
import cairosvg
for s in (16,24,32,48,64,128,256,512):
    cairosvg.svg2png(url='scriptforge.svg', write_to=f'scriptforge-{s}.png',
                     output_width=s, output_height=s)
"
python3 make_ico.py              # rebuild the Windows .ico
./install.sh --desktop-only      # reinstall the icon
```

---

<div align="center">

**ScriptForge** — any script → a real app

built by **AIHAM AM**

</div>