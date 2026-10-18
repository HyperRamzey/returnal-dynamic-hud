@echo off
rem Dynamic HUD for Returnal - starts hud_dynamic.py and keeps the window
rem open on errors. Arguments are passed through (e.g. --dry-run, --calibrate).
cd /d "%~dp0"
python "%~dp0hud_dynamic.py" %*
if not "%ERRORLEVEL%"=="0" pause
