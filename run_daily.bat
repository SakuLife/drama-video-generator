@echo off
chcp 932 >nul
setlocal
cd /d "%~dp0"
rem ~13-min drama video (3_drama-video-generator). Called by Task Scheduler (drama_daily, 04:00).
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

rem exit 9 = already uploaded today (logon trigger re-runs this). Retry once on failure:
rem finished images/audio are reused, so a retry only redoes the failed part (2026-10-01 MemoryError).
"%PY%" main.py --auto --upload >> "logs\daily.log" 2>&1
set "RC=%ERRORLEVEL%"
if "%RC%"=="9" goto stats
rem exit 7 = readings pending (claude -p limit). drama_reading_retry resumes it at night.
if "%RC%"=="7" goto stats
if "%RC%"=="0" goto stats
echo RETRY after exit %RC% >> "logs\daily.log"
"%PY%" main.py --auto --upload >> "logs\daily.log" 2>&1
set "RC=%ERRORLEVEL%"

:stats
rem Daily view/retention snapshot (data\stats.jsonl). Weekly report to Discord on Monday.
"%PY%" scripts\collect_stats.py >> "logs\daily.log" 2>&1
for /f %%d in ('powershell -NoProfile -Command "(Get-Date).DayOfWeek"') do set "DOW=%%d"
if /i "%DOW%"=="Monday" "%PY%" scripts\analyze.py --notify >> "logs\daily.log" 2>&1
if "%RC%"=="9" exit /b 0
if "%RC%"=="7" exit /b 0
exit /b %RC%
