[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$Root,
    [switch]$RemoveNodeModules
)

$ErrorActionPreference = "Stop"
$ScriptRoot = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }

if (-not $Root) {
    $Root = $ScriptRoot
}

if (-not (Test-Path -LiteralPath $Root)) {
    throw "Root path not found: $Root"
}

$resolvedRoot = (Resolve-Path -LiteralPath $Root).Path

$directoryNames = @(
    "__pycache__",
    ".pytest_cache",
    ".svelte-kit",
    ".npm-cache"
)

if ($RemoveNodeModules) {
    $directoryNames += "node_modules"
}

$fileNames = @(
    "tsconfig.tsbuildinfo",
    "predictions_runtime_path.txt"
)

Write-Host "Cleaning generated files under: $resolvedRoot"

foreach ($dirName in $directoryNames) {
    Get-ChildItem -LiteralPath $resolvedRoot -Directory -Recurse -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -eq $dirName -or $_.Name -like "pytest-cache-files-*" } |
        ForEach-Object {
            if ($PSCmdlet.ShouldProcess($_.FullName, "Remove generated directory")) {
                Remove-Item -LiteralPath $_.FullName -Recurse -Force
            }
        }
}

foreach ($fileName in $fileNames) {
    Get-ChildItem -LiteralPath $resolvedRoot -File -Recurse -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -eq $fileName } |
        ForEach-Object {
            if ($PSCmdlet.ShouldProcess($_.FullName, "Remove generated file")) {
                Remove-Item -LiteralPath $_.FullName -Force
            }
        }
}

Write-Host "Generated-file cleanup complete."
