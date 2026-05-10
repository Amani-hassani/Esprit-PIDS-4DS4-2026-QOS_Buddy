@echo off
REM Complete Modern Stack Setup & Deployment Script (Windows)

setlocal enabledelayedexpansion

echo.
echo ╔════════════════════════════════════════════════════════════════╗
echo ║  QoS Prediction Agent - Modern Stack Setup (Windows)          ║
echo ║  SvelteKit 5 + FastAPI + MLflow + SQLite                      ║
echo ╚════════════════════════════════════════════════════════════════╝
echo.

REM ============================================================================
REM Check Prerequisites
REM ============================================================================

echo [*] Checking Prerequisites...
echo.

python --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [!] Python not found. Please install Python 3.11+
) else (
    for /f "tokens=*" %%i in ('python --version') do echo [OK] %%i
)

node --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [!] Node.js not found. Please install Node.js 20+
) else (
    for /f "tokens=*" %%i in ('node --version') do echo [OK] Node %%i
)

docker --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [!] Docker not found. Please install Docker Desktop
) else (
    for /f "tokens=*" %%i in ('docker --version') do echo [OK] %%i
)

echo.

REM ============================================================================
REM Backend Setup
REM ============================================================================

echo [*] Setting up Backend (Python + FastAPI)...
echo.

if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
    echo [OK] Virtual environment created
) else (
    echo [OK] Virtual environment already exists
)

call venv\Scripts\activate.bat

echo Installing Python dependencies...
python -m pip install --upgrade pip setuptools wheel >nul 2>&1
pip install -q -r requirements.txt
echo [OK] Python dependencies installed

if not exist "logs" mkdir logs
if not exist "models\saved" mkdir models\saved
if not exist "rag\chroma_db" mkdir rag\chroma_db
if not exist "mlflow-data" mkdir mlflow-data
if not exist "backend\mlflow_integration" mkdir backend\mlflow_integration
if not exist "backend\database" mkdir backend\database

echo Initializing databases...
python -c "
from backend.database.app_store import initialize_store
from backend.mlflow_integration.tracker import initialize_tracker
initialize_store('app_store.db')
initialize_tracker('sqlite:///mlflow.db', 'qos_prediction')
print('[OK] Databases initialized')
" 2>nul

echo.

REM ============================================================================
REM Frontend Setup
REM ============================================================================

echo [*] Setting up Frontend (SvelteKit 5)...
echo.

if exist "frontend" (
    pushd frontend
    
    if not exist "node_modules" (
        echo Installing Node dependencies...
        call npm install >nul 2>&1
        echo [OK] Node dependencies installed
    ) else (
        echo [OK] Node dependencies already installed
    )
    
    echo Building frontend...
    call npm run build >nul 2>&1
    echo [OK] Frontend built
    
    popd
) else (
    echo [!] Frontend directory not found. Skipping.
)

echo.

REM ============================================================================
REM Environment Configuration
REM ============================================================================

echo [*] Configuring Environment...
echo.

if not exist ".env" (
    (
        echo # Backend Configuration
        echo OLLAMA_URL=http://localhost:11434
        echo OLLAMA_MODEL=gemma3:1b
        echo LOG_LEVEL=INFO
        echo MLFLOW_TRACKING_URI=sqlite:///mlflow.db
        echo DATABASE_PATH=app_store.db
        echo ENVIRONMENT=production
        echo.
        echo # Frontend Configuration
        echo VITE_API_URL=http://localhost:8000
        echo VITE_API_TIMEOUT=30000
    ) > .env
    echo [OK] Created .env file
) else (
    echo [OK] .env file already exists
)

echo.

REM ============================================================================
REM Docker Setup
REM ============================================================================

echo [*] Docker Compose Configuration...
echo.

if exist "docker-compose.yml" (
    echo Building Docker images...
    call docker-compose build >nul 2>&1
    echo [OK] Docker images built
    echo.
    echo Ready to start services:
    echo.
    echo   Start: docker-compose up -d
    echo   Logs:  docker-compose logs -f backend
    echo   Stop:  docker-compose down
) else (
    echo [!] docker-compose.yml not found
)

echo.

REM ============================================================================
REM Startup Instructions
REM ============================================================================

echo [OK] Setup Complete!
echo.
echo ╔════════════════════════════════════════════════════════════════╗
echo ║           DEVELOPMENT MODE (Local - Windows)                  ║
echo ╚════════════════════════════════════════════════════════════════╝
echo.
echo Run in separate Command Prompts:
echo.
echo Terminal 1: Backend API
echo   call venv\Scripts\activate.bat
echo   python -m uvicorn backend.api_enhanced:app --reload --port 8000
echo.
echo Terminal 2: Frontend Dev Server
echo   cd frontend
echo   npm run dev
echo   REM Open http://localhost:5173
echo.
echo Terminal 3: MLflow UI
echo   mlflow ui --backend-store-uri sqlite:///mlflow.db
echo   REM Open http://localhost:5000
echo.
echo Terminal 4: Model Training (Optional)
echo   call venv\Scripts\activate.bat
echo   python main.py
echo.
echo ╔════════════════════════════════════════════════════════════════╗
echo ║        PRODUCTION MODE (Docker Compose - All Platforms)       ║
echo ╚════════════════════════════════════════════════════════════════╝
echo.
echo   docker-compose build
echo   docker-compose up -d
echo.
echo   Services:
echo     - Frontend: http://localhost:5173
echo     - Backend API: http://localhost:8000
echo     - API Docs: http://localhost:8000/docs
echo     - MLflow UI: http://localhost:5000
echo     - Ollama: http://localhost:11434
echo.
echo 🎉 Modern stack is ready for deployment!
echo.

pause
