#Requires -RunAsAdministrator
param(
    [string]$InstallPath = "C:\zkteco-agent",
    [string]$ServiceName = "ZKTecoAgent",
    [string]$NssmPath = "C:\nssm\nssm.exe"
)

$ErrorActionPreference = "Stop"

function Assert-Prerequisite {
    param([string]$Label, [scriptblock]$Test, [string]$Remedy)
    if (-not (& $Test)) {
        throw "$Label`n  -> $Remedy"
    }
    Write-Host "[ok] $Label" -ForegroundColor Green
}

Assert-Prerequisite -Label "Python is on PATH" `
    -Test { Get-Command python -ErrorAction SilentlyContinue } `
    -Remedy "Install Python 3.10+ from python.org and tick 'Add python.exe to PATH'."

Assert-Prerequisite -Label "NSSM is present at $NssmPath" `
    -Test { Test-Path $NssmPath } `
    -Remedy "Download NSSM from https://nssm.cc/download and extract win64\nssm.exe to $NssmPath"

Assert-Prerequisite -Label "Agent source is present at $InstallPath" `
    -Test { Test-Path (Join-Path $InstallPath "src\main.py") } `
    -Remedy "Copy or clone the repository to $InstallPath first."

$envFile = Join-Path $InstallPath ".env"
Assert-Prerequisite -Label ".env exists" `
    -Test { Test-Path $envFile } `
    -Remedy "Copy .env.example to .env and fill in ODOO_URL, ODOO_DB, ODOO_USER_LOGIN and ODOO_API_KEY."

Set-Location $InstallPath

$venvPython = Join-Path $InstallPath ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    python -m venv .venv
}

Write-Host "Installing dependencies..." -ForegroundColor Cyan
& $venvPython -m pip install --quiet --upgrade pip
& $venvPython -m pip install --quiet -r requirements.txt

Write-Host "Preventing the machine from sleeping..." -ForegroundColor Cyan
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0

if (& $NssmPath status $ServiceName 2>$null) {
    Write-Host "Removing existing service..." -ForegroundColor Yellow
    & $NssmPath stop $ServiceName confirm | Out-Null
    & $NssmPath remove $ServiceName confirm | Out-Null
}

Write-Host "Registering service $ServiceName..." -ForegroundColor Cyan
& $NssmPath install $ServiceName $venvPython
& $NssmPath set $ServiceName AppParameters "-m src.main"
& $NssmPath set $ServiceName AppDirectory $InstallPath
& $NssmPath set $ServiceName DisplayName "ZKTeco Attendance Agent"
& $NssmPath set $ServiceName Description "Reads ZKTeco punches on the LAN and pushes them to Odoo"
& $NssmPath set $ServiceName Start SERVICE_AUTO_START
& $NssmPath set $ServiceName AppExit Default Restart
& $NssmPath set $ServiceName AppRestartDelay 15000
& $NssmPath set $ServiceName AppStdout (Join-Path $InstallPath "logs\service-out.log")
& $NssmPath set $ServiceName AppStderr (Join-Path $InstallPath "logs\service-err.log")
& $NssmPath set $ServiceName AppRotateFiles 1
& $NssmPath set $ServiceName AppRotateBytes 5242880

& $NssmPath start $ServiceName
Start-Sleep -Seconds 5
& $NssmPath status $ServiceName

Write-Host ""
Write-Host "Installed. Follow the log with:" -ForegroundColor Green
Write-Host "  Get-Content $InstallPath\logs\zkteco_agent.log -Wait -Tail 30"
