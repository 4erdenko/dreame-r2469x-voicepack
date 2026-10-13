@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
where py >nul 2>&1
if not errorlevel 1 (
    py -3 voicepack.py %*
    goto finish
)
where python >nul 2>&1
if not errorlevel 1 (
    python voicepack.py %*
    goto finish
)
echo Install Python 3.11+ from https://www.python.org/downloads/
exit /b 1
:finish
set result=%errorlevel%
if not "%result%"=="0" pause
exit /b %result%
