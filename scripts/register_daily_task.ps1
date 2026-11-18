<#
.SYNOPSIS
  Create, show or remove the Windows Task Scheduler job "Astra Daily ETL" (current user, no admin rights).

.DESCRIPTION
  The task runs scripts\daily_etl.ps1 every day at -At (default 02:00) as the current user,
  only while that user is signed in (no password is stored). Settings:
  - start as soon as possible if the PC was off or asleep at the set time (StartWhenAvailable);
  - never two runs at once (IgnoreNew; the ETL also holds a database lock);
  - Task Scheduler stops it after 1 hour (the job stops itself after 30 minutes);
  - runs on battery; does not wake the PC.

.EXAMPLE
  .\scripts\register_daily_task.ps1 -Show
.EXAMPLE
  .\scripts\register_daily_task.ps1 -At 02:00
.EXAMPLE
  .\scripts\register_daily_task.ps1 -Unregister
#>
[CmdletBinding()]
param(
    [ValidatePattern('^([01]\d|2[0-3]):[0-5]\d$')][string]$At = '02:00',
    [switch]$Show,
    [switch]$Unregister
)
$ErrorActionPreference = 'Stop'
$name = 'Astra Daily ETL'
$root = Split-Path -Parent $PSScriptRoot
$job = Join-Path $root 'scripts\daily_etl.ps1'

if ($Show) {
    $t = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if (-not $t) { Write-Output "task '$name' is not registered"; exit 0 }
    $i = Get-ScheduledTaskInfo -TaskName $name
    Write-Output "task '$name': state=$($t.State) at=$($t.Triggers[0].StartBoundary) last_run=$($i.LastRunTime) last_result=$($i.LastTaskResult) next_run=$($i.NextRunTime)"
    exit 0
}
if ($Unregister) {
    if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $name -Confirm:$false
        Write-Output "task '$name' removed"
    } else { Write-Output "task '$name' is not registered" }
    exit 0
}

if (-not (Test-Path $job)) { throw "job script not found: $job" }
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -WorkingDirectory $root `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$job`""
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description 'Astra SYNTHETIC platform: daily ETL (scripts\daily_etl.ps1). Logs in logs\etl.' -Force | Out-Null
Write-Output "task '$name' registered: daily at $At as the current user (runs only while signed in)"
