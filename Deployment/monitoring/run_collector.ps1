param()
$ErrorActionPreference = 'Stop'
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "QoS Buddy Data Collector (PowerShell)" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
python --version | Out-Null
python -c "import psutil, numpy" | Out-Null
New-Item -ItemType Directory -Force -Path "data" | Out-Null
New-Item -ItemType Directory -Force -Path "logs" | Out-Null
Write-Host "Dependencies OK" -ForegroundColor Green
Write-Host ""
Write-Host "Choose collection mode:" -ForegroundColor Cyan
Write-Host "[1] Quick Test (15 min, WiFi+Router)"
Write-Host "[2] Baseline (30 min, WiFi+Router)"
Write-Host "[3] Full Collection (60 min, WiFi+QoS)"
Write-Host "[6] Run Scenario (Baseline/Congestion/PacketLoss, WiFi+Router)"
Write-Host "[7] WiFi + Router Metrics (60 min)"
Write-Host "[11] WiFi + Router + iperf3 (60 min, diversified data)"
Write-Host "[12] ALL Scenarios + iperf3 (45 min total: 15 min baseline, 15 min congestion, 15 min packet_loss)"
Write-Host "[13] Structured Pattern (BASELINE + [CONGESTION x2 + NORMAL x2 + PACKET_LOSS x2 + NORMAL x2] repeat)"
Write-Host "[0] Exit"
Write-Host ""
$choice = Read-Host "Enter choice (0-13)"

# Early exit
if ($choice -eq "0") {
    Write-Host "Exiting..." -ForegroundColor Yellow
    exit 0
}

$radioArgs = @()

# For choices that need router credentials (1, 2, 6, 7, 11, 12, 13)
if ($choice -in @("1", "2", "6", "7", "11", "12", "13")) {
    Write-Host ""
    Write-Host "Router Configuration:" -ForegroundColor Cyan
    
    # Auto-detect gateway
    $routerGateway = $null
    try {
        $ipconfig = ipconfig
        $gwLines = $ipconfig | Select-String -Pattern 'Passerelle par d.*faut.*:\s*(\S+)' | Select-Object -First 1
        if ($gwLines) {
            if ($gwLines.Line -match ':\s*(\S+)') {
                $routerGateway = $matches[1]
            }
        } else {
            $gwLines = $ipconfig | Select-String -Pattern 'Default Gateway.*:\s*(\S+)' | Select-Object -First 1
            if ($gwLines) {
                if ($gwLines.Line -match ':\s*(\S+)') {
                    $routerGateway = $matches[1]
                }
            }
        }
    } catch {}
    
    if ($routerGateway) {
        Write-Host "✓ Auto-detected router gateway: $routerGateway" -ForegroundColor Green
    } else {
        $routerGateway = Read-Host "Enter router IP address"
        if ([string]::IsNullOrWhiteSpace($routerGateway)) {
            Write-Host "Router IP required for router metrics collection" -ForegroundColor Red
            exit 1
        }
    }
    
    $routerUsername = Read-Host "Router username [admin]"
    if ([string]::IsNullOrWhiteSpace($routerUsername)) { $routerUsername = "admin" }
    
    $secP = Read-Host "Router password" -AsSecureString
    $cred = New-Object System.Management.Automation.PSCredential ("x", $secP)
    $routerPassword = $cred.GetNetworkCredential().Password
    
    if ([string]::IsNullOrWhiteSpace($routerPassword)) {
        Write-Host "Router password required" -ForegroundColor Red
        exit 1
    }
    
    $radioArgs += @("--router-gateway", $routerGateway, "--router-username", $routerUsername, "--router-password", $routerPassword)
    Write-Host "  Router gateway:    $routerGateway" -ForegroundColor Green
    Write-Host "  Router username:   $routerUsername" -ForegroundColor Green
    
    # For choice 11 and 12, also add iperf3 flag
    if ($choice -eq "11" -or $choice -eq "12") {
        $radioArgs += @("--with-iperf3")
        Write-Host "  iperf3 tests:      enabled (every 60 seconds)" -ForegroundColor Green
    }
}

if ($choice -in @("1", "2", "3", "6", "7", "11", "12", "13")) {
    Write-Host ""
    Write-Host "Collection Profile:" -ForegroundColor Cyan
    Write-Host "==================" -ForegroundColor Cyan
    Write-Host "  WiFi Metrics:      enabled (automatic)"
    if ($radioArgs -contains "--router-gateway") {
        Write-Host "  Router Metrics:    enabled (parallel collection)" -ForegroundColor Green
    }
    if ($choice -eq "11" -or $choice -eq "12") {
        Write-Host "  iperf3 Tests:      enabled (every 60 seconds)" -ForegroundColor Green
    }
    Write-Host "  Duration:          INFINITE (press Ctrl+C to stop)" -ForegroundColor Yellow
    Write-Host "==================" -ForegroundColor Cyan
    Write-Host ""
}

switch ($choice) {
    "1" {
        Write-Host "Running Quick Test (WiFi metrics indefinitely)..." -ForegroundColor Green
        Write-Host "Press Ctrl+C to stop collection" -ForegroundColor Yellow
        & python qos_buddy_collector.py --interval 30 --choice 1 --infinite @radioArgs
    }
    "2" {
        Write-Host "Running Baseline Scenario (indefinitely)..." -ForegroundColor Green
        Write-Host "Press Ctrl+C to stop collection" -ForegroundColor Yellow
        & python qos_buddy_collector.py --scenario baseline --choice 2 --infinite @radioArgs
    }
    "3" {
        Write-Host "Running Full Collection (WiFi+QoS indefinitely)..." -ForegroundColor Green
        Write-Host "Press Ctrl+C to stop collection" -ForegroundColor Yellow
        & python qos_buddy_collector.py --interval 30 --choice 3 --infinite @radioArgs
    }
    "6" {
        Write-Host "Choose scenario: [1] baseline  [2] congestion  [3] packet_loss" -ForegroundColor Cyan
        $s = Read-Host "Enter 1-3"
        if ($s -eq "1") {
            Write-Host "Running Baseline Scenario (indefinitely)..." -ForegroundColor Green
            Write-Host "Press Ctrl+C to stop collection" -ForegroundColor Yellow
            & python qos_buddy_collector.py --scenario baseline --choice 6 --infinite @radioArgs
        }
        elseif ($s -eq "2") {
            Write-Host "Running Congestion Scenario (indefinitely)..." -ForegroundColor Green
            Write-Host "Press Ctrl+C to stop collection" -ForegroundColor Yellow
            & python qos_buddy_collector.py --scenario congestion --choice 6 --infinite @radioArgs
        }
        elseif ($s -eq "3") {
            Write-Host "Running Packet Loss Scenario (indefinitely)..." -ForegroundColor Green
            Write-Host "Press Ctrl+C to stop collection" -ForegroundColor Yellow
            & python qos_buddy_collector.py --scenario packet_loss --choice 6 --infinite @radioArgs
        }
    }
    "7" {
        Write-Host "Running WiFi + Router Metrics (indefinitely)..." -ForegroundColor Green
        Write-Host "Press Ctrl+C to stop collection" -ForegroundColor Yellow
        & python qos_buddy_collector.py --interval 30 --choice 7 --infinite @radioArgs
    }
    "11" {
        Write-Host "Running WiFi + Router + iperf3 (indefinitely)..." -ForegroundColor Green
        Write-Host "Press Ctrl+C to stop collection" -ForegroundColor Yellow
        & python qos_buddy_collector.py --interval 30 --choice 11 --infinite --with-iperf3 @radioArgs
    }
    "12" {
        Write-Host "Running ALL Scenarios + iperf3 (INFINITE loop with diversified data)..." -ForegroundColor Green
        Write-Host "Scenarios: [1] Baseline -> [2] Congestion -> [3] Normal (passive) -> [4] Packet Loss -> repeat" -ForegroundColor Cyan
        Write-Host "Each scenario ~5 minutes | iperf3 tests every 60 seconds | Diversified training data" -ForegroundColor Cyan
        Write-Host "Press Ctrl+C to stop collection" -ForegroundColor Yellow
        & python qos_buddy_collector.py --choice 12 --infinite --all-scenarios @radioArgs
    }
    "13" {
        Write-Host "Running Structured Pattern Collection (INFINITE loop)..." -ForegroundColor Green
        Write-Host "Pattern: BASELINE (60s) -> [CONGESTION x2 + NORMAL x2 + PACKET_LOSS x2 + NORMAL x2] (30s each, repeat)" -ForegroundColor Cyan
        Write-Host "All scenarios and data collection run SIMULTANEOUSLY for realistic impact measurement" -ForegroundColor Cyan
        Write-Host "Press Ctrl+C to stop collection" -ForegroundColor Yellow
        & python qos_buddy_collector.py --choice 13 --infinite --structured-pattern @radioArgs
    }
    default {
        Write-Host "Invalid choice" -ForegroundColor Red
        exit 1
    }
}
Write-Host ""
Write-Host "Done." -ForegroundColor Green
