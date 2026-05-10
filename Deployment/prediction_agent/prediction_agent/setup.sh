#!/bin/bash
# Complete Modern Stack Setup & Deployment Script

set -e

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║  QoS Prediction Agent - Modern Stack Setup                    ║"
echo "║  SvelteKit 5 + FastAPI + MLflow + SQLite                      ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print section headers
print_section() {
    echo ""
    echo -e "${BLUE}▸ $1${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# Function to print success
print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

# Function to print warning
print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

# ============================================================================
# Check Prerequisites
# ============================================================================

print_section "Checking Prerequisites"

# Check Docker
if ! command -v docker &> /dev/null; then
    print_warning "Docker not found. Please install Docker Desktop"
else
    print_success "Docker installed: $(docker --version)"
fi

# Check Node.js
if ! command -v node &> /dev/null; then
    print_warning "Node.js not found. Please install Node.js 20+"
else
    print_success "Node.js installed: $(node --version)"
fi

# Check Python
if ! command -v python3 &> /dev/null; then
    print_warning "Python 3 not found. Please install Python 3.11+"
else
    print_success "Python installed: $(python3 --version)"
fi

# ============================================================================
# Backend Setup
# ============================================================================

print_section "Setting up Backend (Python + FastAPI)"

# Create Python virtual environment
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    print_success "Virtual environment created"
else
    print_success "Virtual environment already exists"
fi

# Activate virtual environment
source venv/bin/activate 2>/dev/null || . venv/Scripts/activate

# Install Python dependencies
echo "Installing Python dependencies..."
pip install --upgrade pip setuptools wheel > /dev/null
pip install -q -r requirements.txt
print_success "Python dependencies installed"

# Create backend directories
mkdir -p logs models/saved rag/chroma_db mlflow-data backend/mlflow_integration backend/database

# Initialize databases
echo "Initializing databases..."
python3 -c "
from backend.database.app_store import initialize_store
from backend.mlflow_integration.tracker import initialize_tracker
initialize_store('app_store.db')
initialize_tracker('sqlite:///mlflow.db', 'qos_prediction')
print('Databases initialized')
" 2>/dev/null
print_success "Databases initialized"

# ============================================================================
# Frontend Setup
# ============================================================================

print_section "Setting up Frontend (SvelteKit 5)"

# Check if frontend directory exists
if [ -d "frontend" ]; then
    cd frontend
    
    # Install Node dependencies
    if [ ! -d "node_modules" ]; then
        echo "Installing Node dependencies..."
        npm install > /dev/null 2>&1
        print_success "Node dependencies installed"
    else
        print_success "Node dependencies already installed"
    fi
    
    # Build frontend
    echo "Building frontend..."
    npm run build > /dev/null 2>&1
    print_success "Frontend built successfully"
    
    cd ..
else
    print_warning "Frontend directory not found. Skipping frontend setup."
fi

# ============================================================================
# Environment Configuration
# ============================================================================

print_section "Configuring Environment"

# Create .env file if it doesn't exist
if [ ! -f ".env" ]; then
    cat > .env << 'EOF'
# Backend Configuration
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=gemma3:1b
LOG_LEVEL=INFO
MLFLOW_TRACKING_URI=sqlite:///mlflow.db
DATABASE_PATH=app_store.db
ENVIRONMENT=production

# Frontend Configuration
VITE_API_URL=http://localhost:8000
VITE_API_TIMEOUT=30000
EOF
    print_success "Created .env file"
else
    print_success ".env file already exists"
fi

# ============================================================================
# Docker Setup
# ============================================================================

print_section "Docker Compose Configuration"

if [ -f "docker-compose.yml" ]; then
    echo "Building Docker images..."
    docker-compose build > /dev/null 2>&1
    print_success "Docker images built"
    
    echo ""
    echo -e "${YELLOW}Ready to start services:${NC}"
    echo ""
    echo "  Start all services:"
    echo "    docker-compose up -d"
    echo ""
    echo "  View logs:"
    echo "    docker-compose logs -f backend"
    echo "    docker-compose logs -f frontend"
    echo ""
    echo "  Stop all services:"
    echo "    docker-compose down"
    echo ""
else
    print_warning "docker-compose.yml not found"
fi

# ============================================================================
# Startup Instructions
# ============================================================================

print_section "Startup Instructions"

cat << 'EOF'
╔════════════════════════════════════════════════════════════════╗
║              DEVELOPMENT MODE (Local)                         ║
╚════════════════════════════════════════════════════════════════╝

Terminal 1: Backend API
  source venv/bin/activate  # or venv\Scripts\activate on Windows
  python -m uvicorn backend.api_enhanced:app --reload --port 8000

Terminal 2: Frontend Dev Server
  cd frontend
  npm run dev
  # Open http://localhost:5173

Terminal 3: MLflow UI
  mlflow ui --backend-store-uri sqlite:///mlflow.db
  # Open http://localhost:5000

Terminal 4: Model Training (Optional)
  source venv/bin/activate
  python main.py

╔════════════════════════════════════════════════════════════════╗
║           PRODUCTION MODE (Docker Compose)                    ║
╚════════════════════════════════════════════════════════════════╝

  docker-compose build
  docker-compose up -d

  Services:
    - Frontend: http://localhost:5173
    - Backend API: http://localhost:8000
    - API Docs: http://localhost:8000/docs
    - MLflow UI: http://localhost:5000
    - Ollama: http://localhost:11434

╔════════════════════════════════════════════════════════════════╗
║                  FIRST TIME SETUP                             ║
╚════════════════════════════════════════════════════════════════╝

  1. Prepare data:
     Place QoS data in: data/raw/
     Place incidents in: data/incidents/

  2. Train models:
     python main.py

  3. Start development servers (see above)

  4. Access dashboard:
     http://localhost:5173

  5. Monitor experiments:
     http://localhost:5000 (MLflow)
     http://localhost:8000/docs (API)

EOF

print_success "Setup Complete!"
echo ""
echo "🎉 Modern stack is ready for deployment!"
