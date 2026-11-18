@echo off
rem Astra launcher. Same command line in PowerShell and cmd: .\astra <command> [args]
rem   .\astra etl [--dry-run] [--offline]          run the ETL (load to Supabase)
rem   .\astra fix list^|show^|set^|drop^|history ...  fix quarantined rows in the database
rem   .\astra notify check^|preview^|test           Telegram alerts (counts only)
rem   .\astra daily [-DryRun] [-NoNotify]           the scheduled daily job (time limit + log)
rem   .\astra schedule [-Show^|-Unregister^|-At HH:MM]  Task Scheduler entry for the daily job
rem   .\astra check-db                             test the database connection
rem   .\astra test                                  unit tests (.venv-laya)
rem   .\astra laya-test                             real Laya model tests, offline
rem   .\astra laya-api                              start the local Laya API (127.0.0.1)
rem   .\astra laya-eval [args]                      Laya evaluation
rem Each command runs outside a ( ) block, so exit /b returns that command's own exit code.
setlocal
set "ROOT=%~dp0"
set "PYTHONPATH=%ROOT%src"
set "LAYA_PY=%ROOT%.venv-laya\Scripts\python.exe"
set "PS=powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File"
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
if /i "%CMD%"=="daily" goto daily
if /i "%CMD%"=="schedule" goto schedule
if /i "%CMD%"=="check-db" goto checkdb
if /i "%CMD%"=="test" goto test
if /i "%CMD%"=="laya-test" goto layatest
if /i "%CMD%"=="laya-api" goto layaapi
if /i "%CMD%"=="laya-eval" goto layaeval
echo usage: .\astra ^<command^> [args]
echo   etl [--dry-run] [--offline]       run the ETL (load to Supabase)
echo   fix list ^| show ^| set ^| drop ^| history   fix quarantined rows (add -h for help)
echo   notify check ^| preview ^| test    Telegram alerts (add -h for help)
echo   daily [-DryRun] [-NoNotify]       the scheduled daily job (time limit + log in logs\etl)
echo   schedule [-Show ^| -Unregister ^| -At HH:MM]   Task Scheduler entry "Astra Daily ETL"
echo   check-db                          test the database connection
echo   test                              unit tests
echo   laya-test                         real Laya model tests, offline
echo   laya-api                          start the local Laya API
echo   laya-eval [args]                  Laya evaluation
exit /b 2

:etl
python -m astra_etl %CMD%%REST%
exit /b %ERRORLEVEL%

:daily
%PS% "%ROOT%scripts\daily_etl.ps1"%REST%
exit /b %ERRORLEVEL%

:schedule
%PS% "%ROOT%scripts\register_daily_task.ps1"%REST%
exit /b %ERRORLEVEL%

:checkdb
python scripts\check_db_connection.py
exit /b %ERRORLEVEL%

:test
"%LAYA_PY%" -m pytest -q%REST%
exit /b %ERRORLEVEL%

:layatest
set "HF_HUB_OFFLINE=1"
"%LAYA_PY%" -m pytest -q -m laya%REST%
exit /b %ERRORLEVEL%

:layaapi
set "HF_HUB_OFFLINE=1"
"%LAYA_PY%" -m decision_engine.api%REST%
exit /b %ERRORLEVEL%

:layaeval
"%LAYA_PY%" -m decision_engine.evaluation%REST%
exit /b %ERRORLEVEL%
