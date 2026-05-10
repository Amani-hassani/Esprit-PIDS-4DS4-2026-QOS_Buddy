# Build a portable QOS-Buddy demo bundle.
#
# Output:
#   C:\tmp\qos-buddy-demo-package\
#   C:\tmp\qos-buddy-demo-package.zip
#
# The docker-compose.yml in qos-buddy intentionally references sibling agent
# repositories, so this packages the whole expected folder layout, not just
# qos-buddy.

[CmdletBinding()]
param(
    [string]$OutputDir = "C:\tmp",
    [string]$PackageName = "qos-buddy-demo-package",
    [switch]$NoZip
)

$ErrorActionPreference = "Stop"

$qosBuddyRoot = $PSScriptRoot
$projectRoot = Split-Path -Parent $qosBuddyRoot
$stageRoot = Join-Path $OutputDir $PackageName
$zipPath = Join-Path $OutputDir "$PackageName.zip"

$requiredDirs = @(
    "qos-buddy",
    "monitoring",
    "detection agent",
    "Diagnostic agent",
    "prediction_agent",
    "optimization agent"
)

$excludeDirs = @(
    ".git",
    ".hg",
    ".svn",
    ".claude",
    ".venv",
    "venv",
    "env",
    "node_modules",
    ".next",
    "out",
    "dist",
    "build",
    ".turbo",
    ".vercel",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".cache",
    "logs"
)

$excludeFiles = @(
    ".env",
    ".env.local",
    ".env.production",
    "*.pyc",
    "*.pyo",
    "*.log",
    "*.tmp",
    "Thumbs.db",
    ".DS_Store"
)

function Assert-RequiredLayout {
    foreach ($dir in $requiredDirs) {
        $path = Join-Path $projectRoot $dir
        if (-not (Test-Path -LiteralPath $path -PathType Container)) {
            throw "Required folder missing: $path"
        }
    }
}

function Copy-ProjectDir {
    param(
        [Parameter(Mandatory=$true)][string]$Name
    )

    $src = Join-Path $projectRoot $Name
    $dst = Join-Path $stageRoot $Name
    Write-Host "[copy] $Name" -ForegroundColor Cyan
    New-Item -ItemType Directory -Force -Path $dst | Out-Null

    $args = @(
        $src,
        $dst,
        "/MIR",
        "/R:2",
        "/W:2",
        "/NFL",
        "/NDL",
        "/NP",
        "/XD"
    ) + $excludeDirs + @("/XF") + $excludeFiles

    & robocopy @args | Out-Host
    if ($LASTEXITCODE -gt 7) {
        throw "robocopy failed for $Name with exit code $LASTEXITCODE"
    }
}

function Write-DemoEnv {
    $envPath = Join-Path $stageRoot "qos-buddy\.env"
    @"
KEYCLOAK_ADMIN=admin
KEYCLOAK_ADMIN_PASSWORD=admin
POSTGRES_PASSWORD=qos

QOS_MONITORING_MODE=tail

# Safe portable demo default. Turn on only on the target machine after adding
# that machine's own Jira credentials.
QOS_JIRA_ENABLED=false
JIRA_URL=
JIRA_EMAIL=
JIRA_TOKEN=
JIRA_PROJECT_KEY=QOS
"@ | Set-Content -Path $envPath -Encoding ascii
}

function Write-StartHere {
    $scriptPath = Join-Path $stageRoot "START-HERE.ps1"
    @'
[CmdletBinding()]
param(
    [int]$Interval = 10,
    [string]$Scenario = "normal"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$qos = Join-Path $root "qos-buddy"

Write-Host "QOS-Buddy portable demo" -ForegroundColor Cyan
Write-Host "Prerequisites: Docker Desktop running, Python 3.10+, local Ollama with qwen2.5:latest, and internet for first-time Docker image pulls." -ForegroundColor DarkGray

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
'@ | Set-Content -Path $scriptPath -Encoding ascii
}

function Write-PackageReadme {
    $readmePath = Join-Path $stageRoot "README_DEMO_PACKAGE.md"
    @'
# QOS-Buddy Portable Demo

## Requirements

- Windows 10/11
- Docker Desktop running with Linux containers
- Python 3.10 or newer on PATH
- 16 GB RAM recommended
- Local Ollama running on the host with `qwen2.5:latest` installed
- Internet on first run so Docker can pull base images

## Start

Open PowerShell in this folder and run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\START-HERE.ps1
```

Then open:

```text
http://localhost:3000
```

The first run can take a while because Docker builds the local services. LLM calls use your host Ollama service at `localhost:11434`.

## Stop

```powershell
.\qos-buddy\stop.ps1
```

To wipe Docker volumes too:

```powershell
.\qos-buddy\stop.ps1 -RemoveVolumes
```

## Jira

This package ships with Jira disabled and no credentials. To use Jira on the target machine, edit `qos-buddy\.env`, set `QOS_JIRA_ENABLED=true`, and add that machine's Jira URL/email/token/project.

## Troubleshooting

- If Docker says ports are in use, stop anything using ports 3000, 8080, 8081, 8088, 8089, 5432, or 6379.
- If the dashboard is empty after first start, wait 60-90 seconds and hard-refresh the browser.
- Logs are available with `docker compose logs -f gateway shell monitoring` from the `qos-buddy` folder.
'@ | Set-Content -Path $readmePath -Encoding ascii
}

Assert-RequiredLayout

if (-not (Test-Path -LiteralPath $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir | Out-Null
}

$resolvedOutput = (Resolve-Path -LiteralPath $OutputDir).Path
if (-not $stageRoot.StartsWith($resolvedOutput, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to remove staging folder outside output dir: $stageRoot"
}

if (Test-Path -LiteralPath $stageRoot) {
    Write-Host "[clean] $stageRoot" -ForegroundColor Yellow
    Remove-Item -LiteralPath $stageRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $stageRoot | Out-Null

foreach ($dir in $requiredDirs) {
    Copy-ProjectDir -Name $dir
}

Write-DemoEnv
Write-StartHere
Write-PackageReadme

if (-not $NoZip) {
    if (Test-Path -LiteralPath $zipPath) {
        Remove-Item -LiteralPath $zipPath -Force
    }
    Write-Host "[zip] $zipPath" -ForegroundColor Cyan
    Compress-Archive -Path (Join-Path $stageRoot "*") -DestinationPath $zipPath -CompressionLevel Optimal
}

$size = (Get-ChildItem -LiteralPath $stageRoot -Recurse -File -Force | Measure-Object Length -Sum).Sum
Write-Host ""
Write-Host "Package folder: $stageRoot" -ForegroundColor Green
if (-not $NoZip) { Write-Host "Zip archive:    $zipPath" -ForegroundColor Green }
Write-Host ("Staged size:    {0:N1} GB" -f ($size / 1GB)) -ForegroundColor Green
