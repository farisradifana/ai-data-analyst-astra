@echo off
rem Astra launcher. Same command line in PowerShell and cmd: .\astra <command> [args]
rem   .\astra etl [--dry-run] [--offline]          run the ETL (load to Supabase)
rem   .\astra fix list^|show^|set^|drop^|history ...  fix quarantined rows in the database
rem   .\astra notify check^|preview^|test           Telegram alerts (counts only)
rem   .\astra n8n build^|lint^|check-live           the n8n data assistant workflow (doc 35)
rem   .\astra telegram-bot check^|run              Telegram bridge to the data assistant (doc 36)
rem   .\astra n8n-start                             n8n at http://astra.localhost:5698 (Supabase CA trusted)
rem   .\astra daily [-DryRun] [-NoNotify]           the scheduled daily job (time limit + log)
rem   .\astra schedule [-Show^|-Unregister^|-At HH:MM]  Task Scheduler entry for the daily job
rem   .\astra check-db                             test the database connection
rem   .\astra test                                  unit tests (.venv-laya)
rem   .\astra laya-test                             real Laya model tests, offline
rem   .\astra laya-api                              start the local Laya API (127.0.0.1)
rem   .\astra laya-eval [args]                      Laya evaluation
rem   .\astra background install^|start^|status^|stop^|uninstall   n8n, Laya API and bridge at sign-in
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
if /i "%CMD%"=="n8n" goto n8n
if /i "%CMD%"=="telegram-bot" goto tgbot
if /i "%CMD%"=="n8n-start" goto n8nstart
if /i "%CMD%"=="daily" goto daily
if /i "%CMD%"=="schedule" goto schedule
if /i "%CMD%"=="check-db" goto checkdb
if /i "%CMD%"=="test" goto test
if /i "%CMD%"=="laya-test" goto layatest
if /i "%CMD%"=="laya-api" goto layaapi
if /i "%CMD%"=="laya-eval" goto layaeval
if /i "%CMD%"=="background" goto background
echo usage: .\astra ^<command^> [args]
echo   etl [--dry-run] [--offline]       run the ETL (load to Supabase)
echo   fix list ^| show ^| set ^| drop ^| history   fix quarantined rows (add -h for help)
echo   notify check ^| preview ^| test    Telegram alerts (add -h for help)
echo   n8n build ^| lint ^| check-live   the n8n data assistant workflow (doc 35)
echo   telegram-bot check ^| run    Telegram bridge to the data assistant (doc 36)
echo   n8n-start                         start n8n at http://astra.localhost:5698 (Supabase CA trusted)
echo   daily [-DryRun] [-NoNotify]       the scheduled daily job (time limit + log in logs\etl)
echo   schedule [-Show ^| -Unregister ^| -At HH:MM]   Task Scheduler entry "Astra Daily ETL"
echo   check-db                          test the database connection
echo   test                              unit tests
echo   laya-test                         real Laya model tests, offline
echo   laya-api                          start the local Laya API
echo   laya-eval [args]                  Laya evaluation
echo   background install ^| start ^| status ^| stop ^| uninstall   n8n, Laya API and bridge in the background at sign-in
exit /b 2

:etl
python -m astra_etl %CMD%%REST%
exit /b %ERRORLEVEL%

:n8n
python -m astra_n8n%REST%
exit /b %ERRORLEVEL%

:tgbot
python -m astra_bot%REST%
exit /b %ERRORLEVEL%

:n8nstart
rem Separate n8n for Astra: editor on http://127.0.0.1:5698 only (not reachable from other machines),
rem own data folder %USERPROFILE%\.n8n-astra (outside the repo: it holds credentials and the encryption
rem key), so it can run next to the other n8n on 5688. Trusts the Supabase CA so the Postgres credential
rem can use SSL Require without "Ignore SSL Issues".
set "N8N_USER_FOLDER=%USERPROFILE%\.n8n-astra"
set "N8N_DIAGNOSTICS_ENABLED=false"
set "N8N_PORT=5698"
rem Open it as http://astra.localhost:5698: browser cookies ignore the port, so on 127.0.0.1 the other
rem n8n instances overwrite this one's n8n-auth login cookie (save fails with "Unauthorized").
set "N8N_EDITOR_BASE_URL=http://astra.localhost:5698"
set "N8N_LISTEN_ADDRESS=127.0.0.1"
rem Plain HTTP on a loopback-only port: n8n's secure cookie would be refused on astra.localhost.
rem Safe here because the editor is bound to 127.0.0.1 only. Do not copy this to a reachable n8n.
set "N8N_SECURE_COOKIE=false"
rem Task runner broker: 5699 (the other n8n uses the default 5679), loopback only.
set "N8N_RUNNERS_BROKER_PORT=5699"
set "N8N_RUNNERS_BROKER_LISTEN_ADDRESS=127.0.0.1"
set "NODE_EXTRA_CA_CERTS=%ROOT%secrets\supabase-ca.crt"
rem n8n is a batch shim (n8n.cmd): CALL keeps this script's environment for it.
call n8n start%REST%
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

:background
%PS% "%ROOT%scripts\background.ps1"%REST%
exit /b %ERRORLEVEL%
