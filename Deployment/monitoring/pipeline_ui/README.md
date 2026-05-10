# Pipeline Monitoring UI (FastAPI + React)

Interface web professionnelle pour visualiser en temps reel ton pipeline multi-agents **sans modifier** la logique metier existante ni les formats JSONL.

## 1) Arborescence

```text
pipeline_ui/
  backend/
    app/
      services/
      config.py
      main.py
      models.py
    requirements.txt
  frontend/
    src/
      components/
      hooks/
      pages/
      api.ts
      App.tsx
      types.ts
    package.json
    tailwind.config.ts
  .gitignore
  README.md
```

## 2) Prerequis

- Python 3.10+
- Node.js 18+
- Fichiers JSONL existants a la racine du projet principal:
  - `network_stream.jsonl`
  - `monitoring_events.jsonl`
  - `workflow_actions.jsonl`

## 3) Installation

### Option A - Scripts Windows recommandes (CMD)

Depuis `D:\telechargement\ghassen\pipeline_ui`:

```bat
run_backend.bat
```

Dans un autre terminal:

```bat
run_frontend.bat
```

### Option B - Manuel backend (CMD)

```bat
cd /d D:\telechargement\ghassen\pipeline_ui\backend
py -3.11 -m venv .venv
.\.venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### Option B - Manuel frontend (CMD)

```bat
cd /d D:\telechargement\ghassen\pipeline_ui\frontend
npm install
copy .env.example .env
```

## 4) Lancement

### Terminal 1 - Producer

```powershell
cd D:\telechargement\ghassen
python scraper_producer.py
```

### Terminal 2 - Consumer

```powershell
cd D:\telechargement\ghassen
python monitor_consumer.py --start-at-end
```

### Terminal 3 - Backend UI FastAPI (CMD)

```bat
cd /d D:\telechargement\ghassen\pipeline_ui\backend
.\.venv\Scripts\activate.bat
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### Terminal 4 - Frontend UI React (CMD)

```bat
cd /d D:\telechargement\ghassen\pipeline_ui\frontend
npm run dev
```

UI: `http://127.0.0.1:5173`

## 5) Endpoints API

- `GET /api/summary`
- `GET /api/events`
- `GET /api/events/{event_id}`
- `GET /api/actions`
- `GET /api/actions/comparison`
- `GET /api/logs/raw`
- `GET /api/pipeline/status`

## 6) Robustesse

- Les lignes JSONL invalides sont ignorees.
- Les fichiers manquants sont geres sans crash (retour vide).
- Aucun changement de format JSONL.
- Polling frontend toutes les 2 secondes.
