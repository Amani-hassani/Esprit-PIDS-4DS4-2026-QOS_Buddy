# QOS-Buddy launcher — boots the host-side monitoring producer + the docker stack.
#
#   .\start.ps1                # producer + docker compose up -d
#   .\start.ps1 -NoDocker      # producer only
#   .\start.ps1 -NoProducer    # docker only
#
# The monitoring producer scrapes the host's real network (iperf3, system metrics,
# router probes), so it has to run on the host. The docker `monitoring` service
# tails network_stream.jsonl via volume mount and forwards onto Redis Streams.

[CmdletBinding()]
param(
    [switch]$NoDocker,
    [switch]$NoProducer,
    [int]$Interval = 10,
    [string]$Scenario = "normal",
    [string]$Zone = "Z2",
    [string]$Cell = "C1",
    [string]$Node = "N1"
)

$ErrorActionPreference = "Stop"
$qosBuddyRoot   = $PSScriptRoot
$projectRoot    = Split-Path -Parent $qosBuddyRoot
$monitoringDir  = Join-Path $projectRoot "monitoring"
$logsDir        = Join-Path $qosBuddyRoot "logs"
$pidFile        = Join-Path $logsDir "producer.pid"
$logFile        = Join-Path $logsDir "producer.log"

if (-not (Test-Path $logsDir)) { New-Item -ItemType Directory -Path $logsDir | Out-Null }

function Test-ProducerRunning {
    if (-not (Test-Path $pidFile)) { return $false }
    $existingPid = Get-Content $pidFile -ErrorAction SilentlyContinue
    if (-not $existingPid) { return $false }
    $proc = Get-Process -Id $existingPid -ErrorAction SilentlyContinue
    if (-not $proc) { return $false }
    # Confirm it's actually our producer, not a recycled PID.
    if ($proc.ProcessName -notmatch "python") { return $false }
    return $true
}

function Start-MonitoringProducer {
    if (Test-ProducerRunning) {
        $existingPid = Get-Content $pidFile
        Write-Host "[producer] already running (PID $existingPid). Skipping." -ForegroundColor Yellow
        return
    }

    if (-not (Test-Path $monitoringDir)) {
        throw "Monitoring directory not found: $monitoringDir"
    }

    $producerScript = Join-Path $monitoringDir "qos_buddy_collector.py"
    if (-not (Test-Path $producerScript)) {
        throw "Producer script not found: $producerScript"
    }

    Write-Host "[producer] starting → $logFile" -ForegroundColor Cyan
    $args = @(
        "qos_buddy_collector.py",
        "--duration", "0",
        "--interval", "$Interval",
        "--scenario", $Scenario,
        "--zone", $Zone,
        "--cell", $Cell,
        "--node", $Node
    )
    $proc = Start-Process `
        -FilePath "python" `
        -ArgumentList $args `
        -WorkingDirectory $monitoringDir `
        -RedirectStandardOutput $logFile `
        -RedirectStandardError (Join-Path $logsDir "producer.err.log") `
        -WindowStyle Hidden `
        -PassThru
    $proc.Id | Out-File -Encoding ascii -NoNewline $pidFile
    Write-Host "[producer] started (PID $($proc.Id))." -ForegroundColor Green
}

function Start-DockerStack {
    Push-Location $qosBuddyRoot
    try {
        Write-Host "[docker] compose up -d --build" -ForegroundColor Cyan
        & docker compose up -d --build
        if ($LASTEXITCODE -ne 0) { throw "docker compose up -d --build failed (exit $LASTEXITCODE)" }
        Write-Host "[docker] dashboard → http://localhost:3000" -ForegroundColor Green
    } finally {
        Pop-Location
    }
}

if (-not $NoProducer) { Start-MonitoringProducer }
if (-not $NoDocker)   { Start-DockerStack }

Write-Host ""
Write-Host "All set. Tail producer:  Get-Content -Wait '$logFile'" -ForegroundColor DarkGray
Write-Host "Stop everything:        .\stop.ps1" -ForegroundColor DarkGray
