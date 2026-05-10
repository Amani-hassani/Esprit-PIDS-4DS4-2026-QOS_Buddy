[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$composeDir = Join-Path $root "qos-buddy"

function Write-Section {
    param([string]$Name)
    Write-Host ""
    Write-Host "== $Name ==" -ForegroundColor Cyan
}

function Invoke-Json {
    param(
        [string]$Container,
        [string]$Python
    )
    docker exec $Container python -c $Python
}

Push-Location $composeDir
try {
    Write-Section "Compose"
    docker compose ps

    Write-Section "Prediction Health"
    Invoke-Json "qos-prediction" @"
import urllib.request, json
data = json.load(urllib.request.urlopen('http://localhost:8000/api/health/full', timeout=10))
summary = {
    'status': data.get('status'),
    'models_ready': data.get('models', {}).get('ready'),
    'missing_models': data.get('models', {}).get('missing_artifacts'),
    'mlflow': data.get('mlflow', {}).get('status'),
    'mlflow_uri': data.get('mlflow', {}).get('tracking_uri'),
    'llm_available': data.get('llm', {}).get('available'),
    'storage': data.get('storage', {}).get('status'),
}
print(json.dumps(summary, indent=2))
"@

    Write-Section "Prediction ChromaDB"
    Invoke-Json "qos-prediction" @"
import chromadb, json
client = chromadb.PersistentClient(path='/app/rag/chroma_db')
collections = [c.name for c in client.list_collections()]
count = client.get_collection('qos_incidents').count() if 'qos_incidents' in collections else 0
print(json.dumps({'collections': collections, 'qos_incidents': count}, indent=2))
"@

    Write-Section "Optimization MLflow"
    Invoke-Json "qos-optimization" @"
import urllib.request, json
req = urllib.request.Request(
    'http://localhost:8000/api/ops/mlops',
    headers={'Authorization': 'Bearer viewer-dev-token'},
)
data = json.load(urllib.request.urlopen(req, timeout=10))
print(json.dumps({
    'available': data.get('status', {}).get('available'),
    'runs': len(data.get('recent_runs', [])),
    'traces': len(data.get('recent_traces', [])),
    'artifact_location': data.get('status', {}).get('artifact_location'),
}, indent=2))
"@

    Write-Section "MLflow Artifact Files"
    Invoke-Json "qos-optimization" @"
import os, json
root = '/root/.codex/memories/pi-v1/mlartifacts'
files = []
for base, _, names in os.walk(root):
    for name in names:
        files.append(os.path.relpath(os.path.join(base, name), root))
print(json.dumps({
    'service': 'optimization',
    'artifact_root': root,
    'artifact_files': len(files),
    'sample': files[:6],
}, indent=2))
"@

    Invoke-Json "qos-prediction" @"
import os, json
from mlflow.tracking import MlflowClient
tracking_uri = 'sqlite:////app/mlflow-data/mlflow.db'
client = MlflowClient(tracking_uri)
experiments = client.search_experiments()
runs = client.search_runs([e.experiment_id for e in experiments], max_results=20) if experiments else []
root = '/app/mlflow-data/mlruns'
files = []
if os.path.exists(root):
    for base, _, names in os.walk(root):
        for name in names:
            files.append(os.path.relpath(os.path.join(base, name), root))
print(json.dumps({
    'service': 'prediction',
    'tracking_uri': tracking_uri,
    'runs_sampled': len(runs),
    'artifact_root': root,
    'artifact_files': len(files),
    'note': 'Zero runs is OK until prediction emits a forecast/logged run.',
}, indent=2))
"@

    Write-Section "Vector Memory"
    Write-Host "Qdrant is not configured in this SSD compose stack; prediction incident memory uses ChromaDB."

    Write-Section "Recent Bridge Logs"
    docker compose logs --tail 25 detection-bridge diagnostic-bridge prediction-bridge optimization-bridge
} finally {
    Pop-Location
}
