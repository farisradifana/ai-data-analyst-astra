<#
.SYNOPSIS
  Runs the Astra services in the background at sign-in: n8n, the Laya API and the Telegram bridge.

.DESCRIPTION
  -Action Start      Supervisor. The Startup-folder VBS runs it hidden. It starts each service through
                     astra.cmd, without a window, and restarts it when it stops. A second supervisor exits at once.
  -Action Stop       Stops the supervisor and every service it started. Services started by hand are left alone.
  -Action Status     Shows the supervisor and each service.
  -Action Install    Writes astra-background.vbs to the user's Startup folder (runs Start at sign-in).
  -Action Uninstall  Removes that VBS file.

  Services (all on loopback only, see each command's docs):
    n8n     .\astra n8n-start                        127.0.0.1:5698
    laya    .\astra laya-api                         127.0.0.1:8765
    bridge  .\astra telegram-bot run --minutes 1440  outbound only; started after n8n answers (max 3 minutes)

  Rules:
  - A service that already runs (port in use, or a bridge started by hand) is not started twice. The supervisor
    checks again every minute and takes over when it has stopped.
  - Exit code 2 (configuration error) or 3 (Telegram conflict or webhook set): not restarted.
  - Other exits: restarted after 30 seconds. 5 quick failures in a row (each under 2 minutes): not restarted.
    The bridge ends after 1440 minutes by design and is restarted.
  - Logs in logs\background\ (gitignored): supervisor.log, and <service>.out.log / .err.log, one previous copy kept.
    The bridge logs user ids and timings only, never questions, answers or tokens.

.EXAMPLE
  .\astra background install
  .\astra background start
  .\astra background status
  .\astra background stop
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('Start', 'Stop', 'Status', 'Install', 'Uninstall')][string]$Action = 'Status'
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Launcher = Join-Path $Root 'astra.cmd'
$LogDir = Join-Path $Root 'logs\background'
$SupervisorLog = Join-Path $LogDir 'supervisor.log'
$PidFile = Join-Path $LogDir 'supervisor.pid'
$ChildFile = Join-Path $LogDir 'children.txt'
$VbsPath = Join-Path ([Environment]::GetFolderPath('Startup')) 'astra-background.vbs'
$MutexName = 'Local\AstraBackgroundSupervisor'

$Services = @(
    @{ Name = 'n8n'; Command = 'n8n-start'; Port = 5698; After = $null },
    @{ Name = 'laya'; Command = 'laya-api'; Port = 8765; After = $null },
    @{ Name = 'bridge'; Command = 'telegram-bot run --minutes 1440'; Port = 0; After = 5698 }
)
$PollSeconds = 5
$RestartDelaySeconds = 30
$ExternalRecheckSeconds = 60
$QuickRunSeconds = 120
$MaxQuickFailures = 5
$WaitForDependencySeconds = 180
$NoRestartCodes = @(2, 3)

function Write-Log([string]$Message) {
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    Add-Content -LiteralPath $SupervisorLog -Value ('{0:yyyy-MM-dd HH:mm:ss} {1}' -f (Get-Date), $Message)
}

function Test-Port([int]$Port) {
    $c = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return [bool]$c
}

function Get-BridgeProcess {
    # A bridge started by hand or by this supervisor: python -m astra_bot run ...
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'astra_bot' -and $_.CommandLine -match '\brun\b' }
}

function Test-Running($Svc) {
    if ($Svc.Port -gt 0) { return (Test-Port $Svc.Port) }
    return [bool](Get-BridgeProcess)
}

function Get-SupervisorProcess {
    if (-not (Test-Path -LiteralPath $PidFile)) { return $null }
    $id = 0
    if (-not [int]::TryParse((Get-Content -LiteralPath $PidFile -TotalCount 1), [ref]$id)) { return $null }
    $p = Get-CimInstance Win32_Process -Filter "ProcessId = $id" -ErrorAction SilentlyContinue
    if ($p -and $p.CommandLine -match 'background\.ps1') { return $p }
    return $null
}

function Start-Service-Process($Svc) {
    $out = Join-Path $LogDir ($Svc.Name + '.out.log')
    $err = Join-Path $LogDir ($Svc.Name + '.err.log')
    foreach ($f in @($out, $err)) {
        if (Test-Path -LiteralPath $f) { Move-Item -LiteralPath $f -Destination ($f + '.1') -Force }
    }
    $arguments = '/d /s /c ""' + $Launcher + '" ' + $Svc.Command + '"'
    $p = Start-Process -FilePath $env:ComSpec -ArgumentList $arguments -WorkingDirectory $Root -WindowStyle Hidden `
        -RedirectStandardOutput $out -RedirectStandardError $err -PassThru
    $null = $p.Handle   # keep the handle so ExitCode is available after the process ends
    Add-Content -LiteralPath $ChildFile -Value $p.Id
    return $p
}

function Stop-Tree([int]$Id) {
    & taskkill.exe /T /F /PID $Id 2>&1 | Out-Null
}

function Invoke-Supervisor {
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    $mutex = New-Object System.Threading.Mutex($false, $MutexName)
    $owns = $false
    try {
        try { $owns = $mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $owns = $true }
        if (-not $owns) { Write-Log 'supervisor already running; this start is skipped'; return 0 }
        Set-Content -LiteralPath $PidFile -Value $PID -Encoding ASCII
        Set-Content -LiteralPath $ChildFile -Value @() -Encoding ASCII
        Write-Log "supervisor started (pid $PID)"

        $state = @{}
        foreach ($s in $Services) {
            $state[$s.Name] = @{ Proc = $null; Started = $null; Quick = 0; Done = $false; NextTry = Get-Date;
                External = $false; WaitSince = $null }
        }
        while (@($state.Values | Where-Object { -not $_.Done }).Count -gt 0) {
            $now = Get-Date
            foreach ($s in $Services) {
                $st = $state[$s.Name]
                if ($st.Done) { continue }
                if ($st.Proc) {
                    if (-not $st.Proc.HasExited) { continue }
                    $code = $st.Proc.ExitCode
                    $ran = [int]($now - $st.Started).TotalSeconds
                    $st.Proc = $null
                    if ($NoRestartCodes -contains $code) {
                        $st.Done = $true
                        Write-Log "$($s.Name) exited with code $code after $ran s; not restarted (see $($s.Name).err.log)"
                        continue
                    }
                    if ($ran -lt $QuickRunSeconds) { $st.Quick++ } else { $st.Quick = 0 }
                    if ($st.Quick -ge $MaxQuickFailures) {
                        $st.Done = $true
                        Write-Log "$($s.Name) failed $MaxQuickFailures times in a row (code $code); not restarted"
                        continue
                    }
                    Write-Log "$($s.Name) exited with code $code after $ran s; restart in $RestartDelaySeconds s"
                    $st.NextTry = $now.AddSeconds($RestartDelaySeconds)
                    continue
                }
                if ($now -lt $st.NextTry) { continue }
                if (Test-Running $s) {
                    if (-not $st.External) { Write-Log "$($s.Name) already runs outside the supervisor; checking again every $ExternalRecheckSeconds s" }
                    $st.External = $true
                    $st.NextTry = $now.AddSeconds($ExternalRecheckSeconds)
                    continue
                }
                if ($s.After -and -not (Test-Port $s.After)) {
                    if (-not $st.WaitSince) { $st.WaitSince = $now }
                    if (($now - $st.WaitSince).TotalSeconds -lt $WaitForDependencySeconds) { continue }
                    Write-Log "$($s.Name): port $($s.After) still closed after $WaitForDependencySeconds s; starting anyway"
                }
                $st.WaitSince = $null
                $st.External = $false
                $st.Proc = Start-Service-Process $s
                $st.Started = Get-Date
                Write-Log "$($s.Name) started (pid $($st.Proc.Id)): .\astra $($s.Command)"
            }
            Start-Sleep -Seconds $PollSeconds
        }
        Write-Log 'no service left to supervise; supervisor stops'
        return 1
    } catch {
        Write-Log ('supervisor failed: ' + $_.Exception.Message)
        return 1
    } finally {
        if ($owns) { $mutex.ReleaseMutex() }
        $mutex.Dispose()
    }
}

function Invoke-Stop {
    $sup = Get-SupervisorProcess
    if ($sup) {
        Stop-Tree $sup.ProcessId
        Write-Output "stopped supervisor (pid $($sup.ProcessId))"
    } else {
        Write-Output 'supervisor not running'
    }
    if (Test-Path -LiteralPath $ChildFile) {
        foreach ($line in Get-Content -LiteralPath $ChildFile) {
            $id = 0
            if (-not [int]::TryParse($line, [ref]$id)) { continue }
            $p = Get-CimInstance Win32_Process -Filter "ProcessId = $id" -ErrorAction SilentlyContinue
            # Only the cmd.exe that ran astra.cmd: a reused pid of another program is left alone.
            if ($p -and $p.Name -eq 'cmd.exe' -and $p.CommandLine -match 'astra\.cmd') {
                Stop-Tree $id
                Write-Output "stopped service tree (pid $id)"
            }
        }
        Set-Content -LiteralPath $ChildFile -Value @() -Encoding ASCII
    }
    Write-Log 'stop requested'
}

function Invoke-Status {
    $sup = Get-SupervisorProcess
    if ($sup) { Write-Output "supervisor  running (pid $($sup.ProcessId))" } else { Write-Output 'supervisor  not running' }
    foreach ($s in $Services) {
        $where = if ($s.Port -gt 0) { "127.0.0.1:$($s.Port)" } else { 'outbound only' }
        $run = if (Test-Running $s) { 'running' } else { 'stopped' }
        Write-Output ('{0,-11} {1,-8} {2}' -f $s.Name, $run, $where)
    }
    $vbs = if (Test-Path -LiteralPath $VbsPath) { 'installed' } else { 'not installed' }
    Write-Output "startup     $vbs ($VbsPath)"
    if (Test-Path -LiteralPath $SupervisorLog) {
        Write-Output 'last log lines:'
        Get-Content -LiteralPath $SupervisorLog -Tail 5 | ForEach-Object { "  $_" }
    }
}

function Invoke-Install {
    $target = Join-Path $Root 'scripts\background.ps1'
    $vbs = @"
' Astra background services at sign-in: n8n, Laya API, Telegram bridge (scripts\background.ps1).
' Written by .\astra background install. Remove with .\astra background uninstall.
Option Explicit
Dim shell, fso, target, i
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
target = "$target"
' Drives may take a short time to become available at sign-in.
For i = 1 To 60
  If fso.FileExists(target) Then Exit For
  WScript.Sleep 2000
Next
If Not fso.FileExists(target) Then WScript.Quit 1
shell.Run """" & shell.ExpandEnvironmentStrings("%SystemRoot%") & "\System32\WindowsPowerShell\v1.0\powershell.exe"" -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & target & """ -Action Start", 0, False
"@
    Set-Content -LiteralPath $VbsPath -Value $vbs -Encoding ASCII
    Write-Output "installed $VbsPath"
    Write-Output 'It runs at the next sign-in. Start now without signing out: .\astra background start'
}

function Invoke-Uninstall {
    if (Test-Path -LiteralPath $VbsPath) {
        Remove-Item -LiteralPath $VbsPath
        Write-Output "removed $VbsPath"
    } else {
        Write-Output 'not installed'
    }
    Write-Output 'Running services keep running: .\astra background stop'
}

switch ($Action) {
    'Start' {
        if ([Environment]::UserInteractive -and $Host.Name -eq 'ConsoleHost' -and -not $env:ASTRA_BACKGROUND_CHILD) {
            # From a terminal: launch the supervisor hidden and return.
            if (Get-SupervisorProcess) { Write-Output 'supervisor already running'; exit 0 }
            $env:ASTRA_BACKGROUND_CHILD = '1'
            $ps = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
            $p = Start-Process -FilePath $ps -WindowStyle Hidden -PassThru -ArgumentList @(
                '-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden', '-File', ('"' + $PSCommandPath + '"'), '-Action', 'Start')
            Write-Output "supervisor started in the background (pid $($p.Id)). Check: .\astra background status"
            exit 0
        }
        exit (Invoke-Supervisor)
    }
    'Stop' { Invoke-Stop; exit 0 }
    'Status' { Invoke-Status; exit 0 }
    'Install' { Invoke-Install; exit 0 }
    'Uninstall' { Invoke-Uninstall; exit 0 }
}
