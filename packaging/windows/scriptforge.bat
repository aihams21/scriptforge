@echo off
REM Console launcher. The window build needs no batch file; this exists so
REM people used to typing scriptforge.bat keep working after installing.
setlocal
set "SF=%~dp0..\venv\Scripts\python.exe"
if not exist "%SF%" set "SF=%~dp0..\.venv\Scripts\python.exe"
if not exist "%SF%" (
  echo ScriptForge is not installed here. Run install.ps1 first.
  exit /b 1
)
"%SF%" -c "import sys;from scriptforge.cli import main;sys.exit(main())" %*
