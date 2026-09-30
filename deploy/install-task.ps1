#Requires -RunAsAdministrator
param(
    [string]$InstallPath = "C:\service_zkteco_daemon",
    [string]$TaskName = "ZKTecoAgent",
    [switch]$Remove
)

$ErrorActionPreference = "Stop"

function Write-Step($message) { Write-Host $message -ForegroundColor Cyan }
function Write-Good($message) { Write-Host "[ok] $message" -ForegroundColor Green }
function Write-Bad($message)  { Write-Host "[!!] $message" -ForegroundColor Red }

if ($Remove) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Good "Removed scheduled task $TaskName"
    } else {
        Write-Host "No task named $TaskName"
    }
    exit 0
}

$python = Join-Path $InstallPath ".venv\Scripts\python.exe"
$envFile = Join-Path $InstallPath ".env"
$configFile = Join-Path $InstallPath "config\daemon.yml"
$logDir = Join-Path $InstallPath "logs"

Write-Step "Checking prerequisites..."
if (-not (Test-Path $python))     { Write-Bad "Missing $python. Run: python -m venv .venv ; .venv\Scripts\pip install -r requirements.txt"; exit 1 }
if (-not (Test-Path $envFile))    { Write-Bad "Missing $envFile"; exit 1 }
if (-not (Test-Path $configFile)) { Write-Bad "Missing $configFile"; exit 1 }
Write-Good "Virtualenv, .env and daemon.yml are present"

if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }

Write-Step "Verifying the agent can reach Odoo and both readers..."
& $python (Join-Path $InstallPath "tools\preflight.py")
if ($LASTEXITCODE -ne 0) {
    Write-Bad "Preflight failed. Fix the errors above before installing the task."
    exit 1
}
Write-Good "Preflight passed"

Write-Step "Preventing the machine from sleeping..."
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
Write-Good "Standby and hibernation disabled on AC power"

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Write-Step "Removing the previous task..."
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Write-Step "Registering scheduled task $TaskName..."
$action = New-ScheduledTaskAction -Execute $python -Argument "-m src.main" -WorkingDirectory $InstallPath
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Description "Reads ZKTeco punches on the LAN and pushes them to Odoo" | Out-Null
Write-Good "Task registered, starts automatically at boot"

Write-Step "Starting it now..."
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 20

$task = Get-ScheduledTask -TaskName $TaskName
$info = Get-ScheduledTaskInfo -TaskName $TaskName
Write-Host ""
Write-Host "State        : $($task.State)"
Write-Host "Last run     : $($info.LastRunTime)"
Write-Host "Last result  : $($info.LastTaskResult)  (0 or 267009 = running normally)"

$log = Join-Path $logDir "zkteco_agent.log"
if (Test-Path $log) {
    Write-Host ""
    Write-Step "Latest log lines:"
    Get-Content $log -Tail 15
} else {
    Write-Bad "No log file yet at $log - check the task in Task Scheduler"
}

Write-Host ""
Write-Good "Done. Follow the log with:"
Write-Host "  Get-Content $log -Wait -Tail 30"
Write-Host "Manage with:"
Write-Host "  Get-ScheduledTask -TaskName $TaskName"
Write-Host "  Stop-ScheduledTask -TaskName $TaskName"
Write-Host "  .\deploy\install-task.ps1 -Remove"
