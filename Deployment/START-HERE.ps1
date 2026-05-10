[CmdletBinding()]
param(
    [int]$Interval = 10,
    [string]$Scenario = "normal"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$qos = Join-Path $root "qos-buddy"

Write-Host "QOS-Buddy portable demo" -ForegroundColor Cyan
Write-Host "Prerequisites: Docker Desktop running, Python 3.10+, and internet for first-time image/model pulls." -ForegroundColor DarkGray

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker CLI was not found. Install/start Docker Desktop, then rerun START-HERE.ps1."
}
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python was not found. Install Python 3.10+ and ensure it is on PATH, then rerun START-HERE.ps1."
}

Push-Location $qos
try {
    .\start.ps1 -Interval $Interval -Scenario $Scenario
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "Dashboard: http://localhost:3000" -ForegroundColor Green
Write-Host "Stop:      .\qos-buddy\stop.ps1" -ForegroundColor DarkGray
try { Start-Process "http://localhost:3000" } catch {}
