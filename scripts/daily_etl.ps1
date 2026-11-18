<#
.SYNOPSIS
  Daily ETL job for Windows Task Scheduler: runs `astra etl --trigger SCHEDULED` with a time limit and a log file.

.DESCRIPTION
  - Runs .\astra.cmd etl --trigger SCHEDULED from the project folder.
  - Writes the console output (counts only, no record content) to logs\etl\etl-<yyyyMMdd-HHmmss>.log
    and keeps the newest 30 logs.
  - Stops the run after -TimeoutMinutes (default 30) and sends a Telegram JOB_TIMEOUT alert.
    A database transaction that is cut off is rolled back by PostgreSQL, so nothing half-loaded stays.
  - Exits with the ETL's exit code (0 = ok), or 124 on timeout, so Task Scheduler shows the result.
  - The ETL itself sends ETL_SUCCESS / STALE_SOURCE / ETL_FAILED alerts (see docs\32-telegram-alerts.md).

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\daily_etl.ps1 -DryRun -NoNotify
#>
[CmdletBinding()]
param(
    [ValidateRange(1, 240)][int]$TimeoutMinutes = 30,
    [ValidateRange(0, 3600)][int]$TimeoutSecondsOverride = 0,   # tests only
    [ValidateRange(1, 365)][int]$KeepLogs = 30,
    [switch]$DryRun,
    [switch]$NoNotify
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $root 'logs\etl'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$log = Join-Path $logDir "etl-$stamp.log"
$errLog = Join-Path $logDir "etl-$stamp.err.log"

$etlArgs = @('etl', '--trigger', 'SCHEDULED')
if ($DryRun) { $etlArgs += '--dry-run' }
if ($NoNotify) { $etlArgs += '--no-notify' }
$limit = if ($TimeoutSecondsOverride -gt 0) { $TimeoutSecondsOverride } else { $TimeoutMinutes * 60 }

function Write-Log([string]$text) {
    $line = '{0} {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $text
    Add-Content -Path $log -Value $line -Encoding UTF8
    Write-Output $line
}

$code = 1
$proc = $null
try {
    Write-Log "start: astra $($etlArgs -join ' ') (limit ${limit}s)"
    $proc = Start-Process -FilePath (Join-Path $root 'astra.cmd') -ArgumentList $etlArgs -WorkingDirectory $root `
        -NoNewWindow -PassThru -RedirectStandardOutput "$log.out" -RedirectStandardError $errLog
    $null = $proc.Handle   # PowerShell 5.1 returns no ExitCode unless the handle is opened early
    if (-not $proc.WaitForExit($limit * 1000)) {
        Write-Log "timeout after ${limit}s: stopping the run"
        # astra.cmd starts python as a child: stop the whole tree.
        & taskkill.exe /PID $proc.Id /T /F | Out-Null
        $code = 124
        if (-not $NoNotify) {
            $minutes = [math]::Max(1, [math]::Ceiling($limit / 60))
            & (Join-Path $root 'astra.cmd') notify timeout --minutes $minutes 2>&1 |
                ForEach-Object { Write-Log "notify: $_" }
        }
    } else {
        $proc.WaitForExit()
        $code = $proc.ExitCode
    }
} catch {
    Write-Log "job error: $($_.Exception.GetType().Name)"
    $code = 1
} finally {
    foreach ($f in @("$log.out", $errLog)) {
        if (Test-Path $f) {
            Get-Content -Path $f -Encoding UTF8 | ForEach-Object { Write-Log $_ }
            Remove-Item -Path $f -Force -ErrorAction SilentlyContinue
        }
    }
    Write-Log "end: exit code $code"
    Get-ChildItem -Path $logDir -Filter 'etl-*.log' | Sort-Object Name -Descending |
        Select-Object -Skip $KeepLogs | Remove-Item -Force -ErrorAction SilentlyContinue
}
exit $code
