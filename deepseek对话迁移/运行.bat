@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 migrate.py %*
) else (
    python migrate.py %*
)

rem keep the window open so the result stays visible
pause
