# ============================================
# QoS Buddy - Health Check (Windows)
# ============================================

$API_URL = "http://localhost:8000"
$FRONTEND_URL = "http://localhost"
$MLFLOW_URL = "http://localhost:5000"

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "   📡 QoS Buddy - Health Check" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

function Check-Service {
    param($Name, $Url, $Endpoint = "")
    
    try {
        $fullUrl = "$Url$Endpoint"
        $response = Invoke-WebRequest -Uri $fullUrl -UseBasicParsing -TimeoutSec 5
        Write-Host "✓ $Name" -ForegroundColor Green
        return $true
    } catch {
        Write-Host "✗ $Name" -ForegroundColor Red
        return $false
    }
}

# Vérification des services
Check-Service "Backend API" $API_URL "/api/v1/health"
Check-Service "Frontend" $FRONTEND_URL ""
Check-Service "MLflow" $MLFLOW_URL ""
Check-Service "API Documentation" $API_URL "/docs"

Write-Host ""

# Métriques détaillées
try {
    $response = Invoke-RestMethod -Uri "$API_URL/api/v1/metrics/system" -TimeoutSec 5
    Write-Host "📊 Métriques système:" -ForegroundColor Yellow
    $response | ConvertTo-Json -Depth 3
} catch {
    Write-Host "⚠ Métriques non disponibles" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""