# ============================================
# QoS Buddy - Mise à jour du modèle (Windows)
# ============================================

param(
    [string]$runId,
    [string]$modelDir,
    [float]$threshold,
    [switch]$noBackup,
    [switch]$noReload
)

$MODELS_DIR = ".\backend\models"
$BACKUP_DIR = ".\backend\models\backups"
$API_URL = "http://localhost:8000"

Write-Host ""
Write-Host "============================================" -ForegroundColor Blue
Write-Host "   🔄 Mise à jour du modèle ML" -ForegroundColor Blue
Write-Host "============================================" -ForegroundColor Blue
Write-Host ""

function Log-Message {
    param([string]$Message, [string]$Level = "INFO")
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logEntry = "[$timestamp] [$Level] $Message"
    Write-Host $logEntry
    Add-Content -Path ".\logs\model_updates.log" -Value $logEntry
}

function Backup-CurrentModel {
    if ($noBackup) { return $true }
    
    try {
        New-Item -ItemType Directory -Force -Path $BACKUP_DIR | Out-Null
        
        $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $backupPath = Join-Path $BACKUP_DIR "backup_$timestamp"
        New-Item -ItemType Directory -Force -Path $backupPath | Out-Null
        
        Get-ChildItem -Path $MODELS_DIR -File | Where-Object { $_.Name -ne "backups" } | ForEach-Object {
            Copy-Item $_.FullName -Destination (Join-Path $backupPath $_.Name)
        }
        
        Log-Message "Modèle sauvegardé dans $backupPath"
        return $true
    } catch {
        Log-Message "Erreur lors de la sauvegarde: $_" -Level "ERROR"
        return $false
    }
}

function Update-ModelFiles {
    param([string]$SourceDir)
    
    try {
        Get-ChildItem -Path $SourceDir -File | ForEach-Object {
            Copy-Item $_.FullName -Destination (Join-Path $MODELS_DIR $_.Name) -Force
            Log-Message "Fichier copié: $($_.Name)"
        }
        return $true
    } catch {
        Log-Message "Erreur lors de la copie: $_" -Level "ERROR"
        return $false
    }
}

function Reload-Api {
    if ($noReload) { return $true }
    
    try {
        $body = @{} | ConvertTo-Json
        $response = Invoke-RestMethod -Uri "$API_URL/api/v1/admin/reload-model" -Method Post -Body $body -ContentType "application/json" -TimeoutSec 30
        
        Log-Message "API rechargée - Seuil: $($response.threshold)"
        return $true
    } catch {
        Log-Message "Erreur de connexion à l'API: $_" -Level "ERROR"
        return $false
    }
}

function Update-Threshold {
    param([float]$NewThreshold)
    
    try {
        $body = @{ threshold = $NewThreshold } | ConvertTo-Json
        $response = Invoke-RestMethod -Uri "$API_URL/api/v1/admin/threshold" -Method Put -Body $body -ContentType "application/json" -TimeoutSec 30
        
        Log-Message "Seuil mis à jour: $($response.old_threshold) -> $($response.new_threshold)"
        return $true
    } catch {
        Log-Message "Erreur mise à jour seuil: $_" -Level "ERROR"
        return $false
    }
}

# Backup
if (-not (Backup-CurrentModel)) { exit 1 }

# Création du dossier temporaire
$tempDir = ".\temp_model"
New-Item -ItemType Directory -Force -Path $tempDir | Out-Null

# Copie des modèles
if ($runId) {
    Log-Message "Téléchargement depuis MLflow: $runId"
    # Nécessite d'avoir mlflow installé
    mlflow artifacts download --run-id $runId --dst-path $tempDir
} elseif ($modelDir) {
    if (Test-Path $modelDir) {
        Copy-Item (Join-Path $modelDir "*") -Destination $tempDir -Force
        Log-Message "Modèles copiés depuis $modelDir"
    } else {
        Log-Message "Dossier source inexistant: $modelDir" -Level "ERROR"
        exit 1
    }
} else {
    Log-Message "Spécifiez -runId ou -modelDir" -Level "ERROR"
    exit 1
}

# Mise à jour des fichiers
if (-not (Update-ModelFiles -SourceDir $tempDir)) { exit 1 }

# Mise à jour du seuil
if ($threshold) {
    if (-not (Update-Threshold -NewThreshold $threshold)) { exit 1 }
}

# Nettoyage
Remove-Item -Path $tempDir -Recurse -Force -ErrorAction SilentlyContinue

# Rechargement API
if (-not (Reload-Api)) { exit 1 }

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "✅ Mise à jour terminée avec succès" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""