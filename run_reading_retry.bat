@echo off
setlocal
cd /d "%~dp0"
rem Resume a drama run whose readings (kana) could not be made at 19:30 (claude -p limit).
rem Called by Task Scheduler (drama_reading_retry, 02:00 every 3h). Does nothing if no pending run.
rem ASCII only in this file (see HQ CLAUDE.md .bat rules).
set "PY="
if exist ".venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY for /f "delims=" %%i in ('py -3.11 -c "import sys;print(sys.executable)" 2^>nul') do set "PY=%%i"
set "PYTHONIOENCODING=utf-8"
if not defined PY (
  echo ERROR: python not found
  exit /b 1
)
if not exist "logs" mkdir "logs"
"%PY%" "..\_shared\portable\require_env.py" --dir . --quiet YT_REFRESH_TOKEN GEMINI_API_KEY >> "logs\daily.log" 2>&1
if errorlevel 9 exit /b 0
"%PY%" main.py --resume-pending >> "logs\daily.log" 2>&1
set "RC=%ERRORLEVEL%"
if "%RC%"=="7" exit /b 0
exit /b %RC%
