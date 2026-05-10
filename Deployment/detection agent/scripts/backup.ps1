# ============================================
# QoS Buddy - Script de backup (Windows)
# ============================================

$BACKUP_DIR = ".\backups"
$TIMESTAMP = Get-Date -Format "yyyyMMdd_HHmmss"
$BACKUP_NAME = "qos_buddy_backup_$TIMESTAMP"

Write-Host ""
Write-Host "============================================" -ForegroundColor Blue
Write-Host "   📦 Backup de QoS Buddy" -ForegroundColor Blue
Write-Host "============================================" -ForegroundColor Blue
Write-Host ""

# Création du dossier de backup
New-Item -ItemType Directory -Force -Path "$BACKUP_DIR\$BACKUP_NAME" | Out-Null

# Backup de la base de données
if (Test-Path ".\data\app.db") {
    Copy-Item ".\data\app.db" "$BACKUP_DIR\$BACKUP_NAME\"
    Write-Host "✓ Base de données sauvegardée" -ForegroundColor Green
}

# Backup des modèles
if (Test-Path ".\backend\models") {
    Copy-Item -Recurse ".\backend\models" "$BACKUP_DIR\$BACKUP_NAME\"
    Write-Host "✓ Modèles sauvegardés" -ForegroundColor Green
}

# Backup de la configuration
if (Test-Path ".\.env") {
    Copy-Item ".\.env" "$BACKUP_DIR\$BACKUP_NAME\"
    Write-Host "✓ Configuration sauvegardée" -ForegroundColor Green
}

# Backup des logs
if (Test-Path ".\logs") {
    Copy-Item -Recurse ".\logs" "$BACKUP_DIR\$BACKUP_NAME\"
    Write-Host "✓ Logs sauvegardés" -ForegroundColor Green
}

# Compression
Compress-Archive -Path "$BACKUP_DIR\$BACKUP_NAME\*" -DestinationPath "$BACKUP_DIR\$BACKUP_NAME.zip" -Force
Remove-Item -Path "$BACKUP_DIR\$BACKUP_NAME" -Recurse -Force

Write-Host ""
Write-Host "✅ Backup terminé : $BACKUP_DIR\$BACKUP_NAME.zip" -ForegroundColor Green
Write-Host ""