[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$ExportDir,
    [switch]$SkipImages,
    [switch]$SkipVolumes,
    [switch]$OverwriteVolumes
)

$ErrorActionPreference = "Stop"
$ScriptRoot = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }

if (-not $ExportDir) {
    $ExportDir = Join-Path $ScriptRoot "docker-export"
}

function Test-CommandAvailable {
    param([Parameter(Mandatory = $true)][string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Get-VolumeNameFromArchive {
    param([Parameter(Mandatory = $true)][string]$ArchivePath)

    $name = Split-Path $ArchivePath -Leaf
    if ($name.EndsWith(".tar.gz")) {
        return $name.Substring(0, $name.Length - ".tar.gz".Length)
    }
    return [IO.Path]::GetFileNameWithoutExtension($name)
}

if (-not (Test-CommandAvailable "docker")) {
    throw "Docker is not available in PATH. Start Docker Desktop or install Docker CLI first."
}

if (-not (Test-Path -LiteralPath $ExportDir)) {
    throw "Export directory not found: $ExportDir"
}

$imageArchive = Join-Path $ExportDir "qos-buddy-images.tar"
if (-not $SkipImages) {
    if (Test-Path -LiteralPath $imageArchive) {
        if ($PSCmdlet.ShouldProcess($imageArchive, "Load Docker images")) {
            docker load -i $imageArchive
        }
    }
    else {
        Write-Warning "Image archive not found: $imageArchive"
    }
}

$volumeDir = Join-Path $ExportDir "volumes"
if (-not $SkipVolumes) {
    if (-not (Test-Path -LiteralPath $volumeDir)) {
        Write-Warning "Volume export directory not found: $volumeDir"
        return
    }

    $archives = Get-ChildItem -LiteralPath $volumeDir -Filter "*.tar.gz" -File | Sort-Object Name
    if (-not $archives) {
        Write-Warning "No volume archives found in: $volumeDir"
        return
    }

    foreach ($archive in $archives) {
        $volumeName = Get-VolumeNameFromArchive -ArchivePath $archive.FullName
        $existing = docker volume ls --format "{{.Name}}" | Where-Object { $_ -eq $volumeName }

        if ($existing -and -not $OverwriteVolumes) {
            Write-Host "Skipping existing volume $volumeName. Use -OverwriteVolumes to replace its contents."
            continue
        }

        if (-not $existing) {
            if ($PSCmdlet.ShouldProcess($volumeName, "Create Docker volume")) {
                docker volume create $volumeName | Out-Null
            }
        }

        if ($existing -and $OverwriteVolumes) {
            if ($PSCmdlet.ShouldProcess($volumeName, "Clear existing Docker volume contents")) {
                docker run --rm `
                    -v "${volumeName}:/volume" `
                    alpine:3.20 `
                    sh -c "find /volume -mindepth 1 -maxdepth 1 -exec rm -rf {} +"
            }
        }

        if ($PSCmdlet.ShouldProcess($volumeName, "Restore from $($archive.Name)")) {
            docker run --rm `
                -v "${volumeName}:/volume" `
                -v "${volumeDir}:/backup:ro" `
                alpine:3.20 `
                sh -c "cd /volume && tar xzf /backup/$($archive.Name)"
        }
    }
}

Write-Host "Docker asset restore step complete."
