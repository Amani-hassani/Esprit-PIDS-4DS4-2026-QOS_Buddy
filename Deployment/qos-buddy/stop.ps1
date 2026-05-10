# QOS-Buddy shutdown — stops the host-side producer and the docker stack.
#
#   .\stop.ps1                 # producer + docker compose down
#   .\stop.ps1 -NoDocker       # producer only
#   .\stop.ps1 -NoProducer     # docker only
#   .\stop.ps1 -RemoveVolumes  # also wipe docker volumes

[CmdletBinding()]
param(
    [switch]$NoDocker,
    [switch]$NoProducer,
    [switch]$RemoveVolumes
)

$ErrorActionPreference = "Stop"
$qosBuddyRoot = $PSScriptRoot
$logsDir      = Join-Path $qosBuddyRoot "logs"
$pidFile      = Join-Path $logsDir "producer.pid"

function Stop-MonitoringProducer {
    if (-not (Test-Path $pidFile)) {
        Write-Host "[producer] no PID file. Nothing to stop." -ForegroundColor Yellow
        return
    }
    $producerPid = Get-Content $pidFile -ErrorAction SilentlyContinue
    if (-not $producerPid) {
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
        return
    }
    $proc = Get-Process -Id $producerPid -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Host "[producer] stopping PID $producerPid" -ForegroundColor Cyan
        Stop-Process -Id $producerPid -Force
        Write-Host "[producer] stopped." -ForegroundColor Green
    } else {
        Write-Host "[producer] PID $producerPid is no longer running." -ForegroundColor Yellow
    }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

function Stop-DockerStack {
    Push-Location $qosBuddyRoot
    try {
        if ($RemoveVolumes) {
            Write-Host "[docker] compose down -v" -ForegroundColor Cyan
            & docker compose down -v
        } else {
            Write-Host "[docker] compose down" -ForegroundColor Cyan
            & docker compose down
        }
        if ($LASTEXITCODE -ne 0) { throw "docker compose down failed (exit $LASTEXITCODE)" }
    } finally {
        Pop-Location
    }
}

if (-not $NoProducer) { Stop-MonitoringProducer }
if (-not $NoDocker)   { Stop-DockerStack }

Write-Host "Done." -ForegroundColor Green
