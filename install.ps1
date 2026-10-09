<#
.SYNOPSIS
    ScriptForge installer for Windows 10/11 - by AIHAM AM

.DESCRIPTION
    Creates a private Python environment, installs ScriptForge, and puts
    shortcuts on the Start menu and the Desktop.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File install.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File install.ps1 -Uninstall
#>

[CmdletBinding()]
param(
    [switch]$Uninstall,
    [switch]$NoShortcuts
)

$ErrorActionPreference = 'Stop'
$Root    = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv    = Join-Path $Root '.venv'
$PyExe   = Join-Path $Venv 'Scripts\python.exe'
$Icon    = Join-Path $Root 'packaging\icon\scriptforge.ico'
$StartM  = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
$Desktop = [Environment]::GetFolderPath('Desktop')

function Step($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "  [OK] $m" -ForegroundColor Green }
function Die($m)  { Write-Host "  [X] $m"  -ForegroundColor Red; exit 1 }

# ------------------------------------------------------------------ banner

Write-Host ''
Write-Host '   ___  _____ ____ _   _  _____' -ForegroundColor Green
Write-Host '  / __||  _  |_   _| | | ||  ___|   any script -> a real app' -ForegroundColor Green
Write-Host '  \__ \ | |__  | | | |_| || |_      _   _    | |   ____ ___' -ForegroundColor Green
Write-Host '  |___/ |____| |_|  \__, |___|     | |_| |   | |  / __|  _ \' -ForegroundColor Green
Write-Host '                          |___/     \__, |   | | | (__| | | |' -ForegroundColor Green
Write-Host '   _   _   ___  ____ _    _____      __/ |   |_|  \___|_| |_|' -ForegroundColor Green
Write-Host '  | | | | / _ \|  _ \ |  |_   _|    /____|' -ForegroundColor Green
Write-Host '  | |_| || | | | |_) || | | | |    scriptforge' -ForegroundColor Green
Write-Host '  |  _  || |_| |  _ < | | | | |           AIHAM AM' -ForegroundColor Green
Write-Host '  |_| |_| \___/|_| \_\|_| |_| |_|          bash + python + powershell' -ForegroundColor Green
Write-Host ''

# ------------------------------------------------------------------ uninstall

$Links = @(
    (Join-Path $StartM 'ScriptForge.lnk')
    (Join-Path $Desktop  'ScriptForge.lnk')
)

if ($Uninstall) {
    Step 'Removing ScriptForge shortcuts'
    foreach ($l in $Links) { if (Test-Path $l) { Remove-Item $l -Force; Ok "removed $l" } }
    if (Test-Path $Venv) { Write-Host '  the .venv folder was left in place (delete it if you want)' -ForegroundColor DarkGray }
    Write-Host ''
    Write-Host 'Uninstalled. Your own scripts were never touched.' -ForegroundColor Green
    Write-Host ''
    exit 0
}

# ------------------------------------------------------------------ preflight

Step 'Checking prerequisites'

$py = $null
foreach ($cand in @('python', 'python3', 'py')) {
    try {
        $exe = (Get-Command $cand -ErrorAction Stop).Source
        $v = & $exe -c "import sys;print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($v) { $py = $exe; $pyv = $v; break }
    } catch { }
}
if (-not $py) { Die 'Python 3.10+ not found. Install it from https://www.python.org/downloads/ (tick "Add to PATH").' }
Ok "python $pyv"

# ------------------------------------------------------------------ venv

if (-not (Test-Path $PyExe)) {
    Step 'Creating virtual environment'
    & $py -m venv $Venv
    if (-not (Test-Path $PyExe)) { Die "could not create the environment at $Venv" }
    Ok "created $Venv"
} else {
    Ok 'reusing existing .venv'
}

Step 'Installing dependencies'
& $PyExe -m pip install --quiet --upgrade pip 2>$null
& $PyExe -m pip install --quiet -e $Root
if ($LASTEXITCODE -ne 0) {
    Write-Host '  editable install failed, falling back to plain dependencies' -ForegroundColor DarkGray
    & $PyExe -m pip install --quiet 'bashlex>=0.18' 'textual>=0.60'
    if ($LASTEXITCODE -ne 0) { Die 'dependency install failed - check your internet connection' }
}
Ok 'installed (bashlex, textual)'

# pexpect is POSIX-only; the engine falls back to pipes on Windows by design
& $PyExe -m pip install --quiet pexpect 2>$null
Ok 'optional pexpect skipped on Windows (pipe mode is used instead)'

# ------------------------------------------------------------------ verify

Step 'Verifying the install'

$env:PYTHONPATH = $Root
$SelfTest = @'
import tempfile
from pathlib import Path
from scriptforge.core.parser import analyze, Kind
from scriptforge.core.rewriter import rewrite
from scriptforge.core.runner import IS_WINDOWS, ScriptRunner
from scriptforge.core.parser.ps_adapter import analyze_powershell
from scriptforge.ui import theme

tmp = Path(tempfile.mkdtemp())

py = tmp / "ask.py"
py.write_text('#!/usr/bin/env python3\nt = input("target: ")\nprint("hit", t)\n')
ir = analyze(py)
assert ir.kind is Kind.INTERACTIVE, ir.kind
print("  parser   ok   recovered a python prompt")

ps = tmp / "probe.ps1"
ps.write_text('param([string]$Target)\n$t = Read-Host "port"\nWrite-Host "dial $Target:$t"\n')
ir2 = analyze_powershell(ps)
assert [p.var for p in ir2.prompt_sites] == ["t"], ir2.prompt_sites
assert [a.name for a in ir2.positional_args] == ["Target"], ir2.positional_args
print("  ps       ok   recovered Read-Host + param()")

r = ScriptRunner(py, answers={"t": "10.0.0.1"}, timeout=30).run_plain(args=["x"])
assert r.ok, r.output
print(f"  runner   ok   exit={r.exit_code} windows={IS_WINDOWS}")

print(f"  ui       ok   {theme.version_line()}")
'@
$SelfTest | & $PyExe -
if ($LASTEXITCODE -ne 0) { Die 'self-test failed - the install is not usable' }
Ok 'self-test passed'

# ------------------------------------------------------------------ shortcuts

if (-not $NoShortcuts) {
    Step 'Creating shortcuts'
    $shell = New-Object -ComObject WScript.Shell
    $Target = Join-Path $Venv 'Scripts\scriptforge.exe'
    if (-not (Test-Path $Target)) { $Target = Join-Path $Venv 'Scripts\scriptforge-scriptforge.exe' }
    if (-not (Test-Path $Target)) { $Target = $PyExe }

    foreach ($dir in @($StartM, $Desktop)) {
        if (-not (Test-Path $dir)) { continue }
        $lnk = Join-Path $dir 'ScriptForge.lnk'
        $sc  = $shell.CreateShortcut($lnk)
        $sc.TargetPath       = $Target
        $sc.Arguments        = 'ui'
        $sc.WorkingDirectory = $Root
        $sc.Description      = 'Turn any bash, python or PowerShell script into a usable app'
        if (Test-Path $Icon) { $sc.IconLocation = "$Icon,0" }
        $sc.WindowStyle      = 1   # normal console
        $sc.Save()
        Ok "shortcut -> $lnk"
    }
}

# ------------------------------------------------------------------ done

Write-Host ''
Write-Host 'scriptforge is ready.' -ForegroundColor Green
Write-Host ''
Write-Host '  Run it:   Start menu -> ScriptForge   (or the Desktop shortcut)'
Write-Host '  Or:      .\.venv\Scripts\scriptforge.exe ui'
Write-Host ''
Write-Host '  Try:'
Write-Host '    .\.venv\Scripts\scriptforge.exe scan  $env:USERPROFILE\bin'
Write-Host '    .\.venv\Scripts\scriptforge.exe inspect .\myscript.ps1'
Write-Host ''
Write-Host '  Remove it:  powershell -ExecutionPolicy Bypass -File install.ps1 -Uninstall'
Write-Host ''