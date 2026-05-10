@echo off
REM QoS Buddy - Windows Batch Helper Script
REM Run from cmd.exe or PowerShell

setlocal enabledelayedexpansion

echo.
echo ========================================
echo QoS Buddy Data Collector
echo ========================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python not found. Please install Python 3.8+
    echo Visit: https://www.python.org/downloads/
    pause
    exit /b 1
)

REM Check if dependencies are installed
python -c "import psutil, numpy" >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing dependencies...
    pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo ERROR: Failed to install dependencies
        pause
        exit /b 1
    )
)

REM Create data directory if needed
if not exist "data" mkdir data
if not exist "logs" mkdir logs

echo Dependencies OK.
echo.
echo Choose collection mode:
echo [1] Quick Test (15 min)
echo [2] Baseline (30 min)
echo [3] Full Collection (60 min)
echo [4] Peak Hour Collection (2 hours)
echo [5] Custom Duration
echo [6] Run Scenario
echo [0] Exit
echo.

set /p choice="Enter choice (0-6): "

if "%choice%"=="1" (
    echo Running Quick Test (15 minutes)...
    python qos_buddy_collector.py --duration 15 --interval 30
) else if "%choice%"=="2" (
    echo Running Baseline (30 minutes)...
    python qos_buddy_collector.py --scenario baseline --duration 30
) else if "%choice%"=="3" (
    echo Running Full Collection (60 minutes)...
    python qos_buddy_collector.py --duration 60 --interval 30
) else if "%choice%"=="4" (
    echo Running Peak Hour Collection (120 minutes)...
    python qos_buddy_collector.py --duration 120 --interval 30
) else if "%choice%"=="5" (
    set /p minutes="Enter duration in minutes: "
    set /p interval="Enter interval in seconds (default 30): "
    if "%interval%"=="" set interval=30
    echo Running custom collection (!minutes! minutes, !interval! second intervals)...
    python qos_buddy_collector.py --duration !minutes! --interval !interval!
) else if "%choice%"=="6" (
    echo Choose scenario:
    echo [1] Baseline (normal conditions)
    echo [2] Congestion (high traffic)
    echo [3] Packet Loss (poor conditions)
    echo.
    set /p scenario="Enter scenario (1-3): "
    
    if "!scenario!"=="1" (
        python qos_buddy_collector.py --scenario baseline --duration 15
    ) else if "!scenario!"=="2" (
        python qos_buddy_collector.py --scenario congestion --duration 20
    ) else if "!scenario!"=="3" (
        python qos_buddy_collector.py --scenario packet_loss --duration 20
    ) else (
        echo Invalid choice
    )
) else if "%choice%"=="0" (
    echo Exiting...
    exit /b 0
) else (
    echo Invalid choice
    exit /b 1
)

echo.
REM Check if collection was successful
if %errorlevel% equ 0 (
    echo.
    echo ========================================
    echo Collection Completed Successfully!
    echo ========================================
    echo.
    echo Output files:
    echo   Data:  data\qos_timeseries_*.csv
    echo   Logs:  logs\qos_collector_*.log
    echo.
    set /p analyze="Analyze data now? (y/n): "
    if "!analyze!"=="y" (
        python analyze_qos_data.py
    )
) else (
    echo.
    echo Collection failed. Check logs for details.
    echo Log files: logs\qos_collector_*.log
)

pause
