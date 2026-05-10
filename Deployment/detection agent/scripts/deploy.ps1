# ============================================
# QoS Buddy - Script de déploiement (Windows)
# ============================================

Write-Host ""
Write-Host "============================================" -ForegroundColor Blue
Write-Host "   🚀 QoS Buddy - Déploiement" -ForegroundColor Blue
Write-Host "============================================" -ForegroundColor Blue
Write-Host ""

# Vérification des prérequis
Write-Host "Vérification des prérequis..." -ForegroundColor Yellow

try {
    docker --version | Out-Null
    Write-Host "✓ Docker OK" -ForegroundColor Green
} catch {
    Write-Host "✗ Docker n'est pas installé" -ForegroundColor Red
    exit 1
}

try {
    docker-compose --version | Out-Null
    Write-Host "✓ Docker Compose OK" -ForegroundColor Green
} catch {
    Write-Host "✗ Docker Compose n'est pas installé" -ForegroundColor Red
    exit 1
}

# Création des dossiers
Write-Host "`nCréation des dossiers..." -ForegroundColor Yellow
New-Item -ItemType Directory -Force -Path "data" | Out-Null
New-Item -ItemType Directory -Force -Path "logs" | Out-Null
New-Item -ItemType Directory -Force -Path "mlflow" | Out-Null
New-Item -ItemType Directory -Force -Path "backend/models" | Out-Null
Write-Host "✓ Dossiers créés" -ForegroundColor Green

# Vérification des modèles
Write-Host "`nVérification des modèles..." -ForegroundColor Yellow

if (Test-Path "backend/models/agent_detection.keras") {
    Write-Host "✓ agent_detection.keras trouvé" -ForegroundColor Green
} else {
    Write-Host "⚠ agent_detection.keras manquant" -ForegroundColor Yellow
}

if (Test-Path "backend/models/scaler.pkl") {
    Write-Host "✓ scaler.pkl trouvé" -ForegroundColor Green
} else {
    Write-Host "⚠ scaler.pkl manquant" -ForegroundColor Yellow
}

# Build des images
Write-Host "`nConstruction des images Docker..." -ForegroundColor Yellow
docker-compose build --no-cache

# Démarrage des services
Write-Host "`nDémarrage des services..." -ForegroundColor Yellow
docker-compose up -d

# Attente du démarrage
Write-Host "`nAttente du démarrage des services..." -ForegroundColor Yellow
$maxAttempts = 30
$attempt = 0

while ($attempt -lt $maxAttempts) {
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:8000/api/v1/health" -UseBasicParsing -TimeoutSec 2
        if ($response.StatusCode -eq 200) {
            Write-Host "✓ Backend opérationnel" -ForegroundColor Green
            break
        }
    } catch {
        # Ignorer les erreurs
    }
    $attempt++
    Write-Host -NoNewline "."
    Start-Sleep -Seconds 2
}

if ($attempt -eq $maxAttempts) {
    Write-Host "`n✗ Timeout: Backend non accessible" -ForegroundColor Red
    docker-compose logs backend
    exit 1
}

# Affichage du statut
Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "✅ Déploiement terminé !" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "📍 Accès aux services :" -ForegroundColor Cyan
Write-Host "   📊 Frontend    : http://localhost"
Write-Host "   📡 API Docs    : http://localhost:8000/docs"
Write-Host "   📈 MLflow UI   : http://localhost:5000"
Write-Host "   ❤️ Health      : http://localhost:8000/api/v1/health"
Write-Host ""
Write-Host "📋 Commandes utiles :" -ForegroundColor Cyan
Write-Host "   docker-compose logs -f      # Voir les logs"
Write-Host "   docker-compose down         # Arrêter les services"
Write-Host "   docker-compose restart      # Redémarrer"
Write-Host ""