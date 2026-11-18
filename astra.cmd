@echo off
rem Astra launcher. Same command line in PowerShell and cmd: .\astra <command> [args]
rem   .\astra etl [--dry-run] [--offline]          run the ETL (load to Supabase)
rem   .\astra fix list^|show^|set^|drop^|history ...  fix quarantined rows in the database
rem   .\astra notify check^|preview^|test           Telegram alerts (counts only)
rem   .\astra check-db                             test the database connection
rem   .\astra test                                  unit tests (.venv-laya)
rem   .\astra laya-test                             real Laya model tests, offline
rem   .\astra laya-api                              start the local Laya API (127.0.0.1)
rem   .\astra laya-eval [args]                      Laya evaluation
setlocal
set "ROOT=%~dp0"
set "PYTHONPATH=%ROOT%src"
set "LAYA_PY=%ROOT%.venv-laya\Scripts\python.exe"
cd /d "%ROOT%"
set "CMD=%~1"
rem Collect the arguments after the command (batch %* cannot drop the first one).
set "REST="
:collect
shift
if "%~1"=="" goto dispatch
set REST=%REST% %1
goto collect

:dispatch
if /i "%CMD%"=="etl" goto etl
if /i "%CMD%"=="fix" goto etl
if /i "%CMD%"=="notify" goto etl
if /i "%CMD%"=="check-db" (
  python scripts\check_db_connection.py
  exit /b %ERRORLEVEL%
)
if /i "%CMD%"=="test" (
  "%LAYA_PY%" -m pytest -q %REST%
  exit /b %ERRORLEVEL%
)
if /i "%CMD%"=="laya-test" (
  set "HF_HUB_OFFLINE=1"
  "%LAYA_PY%" -m pytest -q -m laya %REST%
  exit /b %ERRORLEVEL%
)
if /i "%CMD%"=="laya-api" (
  set "HF_HUB_OFFLINE=1"
  "%LAYA_PY%" -m decision_engine.api %REST%
  exit /b %ERRORLEVEL%
)
if /i "%CMD%"=="laya-eval" (
  "%LAYA_PY%" -m decision_engine.evaluation %REST%
  exit /b %ERRORLEVEL%
)
echo usage: .\astra ^<command^> [args]
echo   etl [--dry-run] [--offline]       run the ETL (load to Supabase)
echo   fix list ^| show ^| set ^| drop ^| history   fix quarantined rows (add -h for help)
echo   notify check ^| preview ^| test    Telegram alerts (add -h for help)
echo   check-db                          test the database connection
echo   test                              unit tests
echo   laya-test                         real Laya model tests, offline
echo   laya-api                          start the local Laya API
echo   laya-eval [args]                  Laya evaluation
exit /b 2

:etl
python -m astra_etl %CMD%%REST%
exit /b %ERRORLEVEL%
