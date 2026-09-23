@echo off
chcp 932 >nul
setlocal
cd /d "%~dp0"
rem 30-min drama video (3_drama-video-generator). Called by Task Scheduler (drama_daily, 19:30).
rem Skips silently while YT_REFRESH_TOKEN is empty (see _shared\portable\require_env.py).
rem ASCII only in this file (see HQ CLAUDE.md .bat rules).
set "PY="
if exist ".venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY for /f "delims=" %%i in ('py -3.11 -c "import sys;print(sys.executable)" 2^>nul') do set "PY=%%i"
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
if not defined PY (
  echo ERROR: python not found
  exit /b 1
)
if not exist "logs" mkdir "logs"

"%PY%" "..\_shared\portable\require_env.py" --dir . --quiet YT_REFRESH_TOKEN GEMINI_API_KEY >> "logs\daily.log" 2>&1
if errorlevel 9 exit /b 0

"%PY%" main.py --auto --upload >> "logs\daily.log" 2>&1
exit /b %ERRORLEVEL%
