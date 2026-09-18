# Wind Turbine Site Suitability API

FastAPI service for AHP + Random Forest + OpenRouteService site suitability in the Sindh Wind Corridor.

Pipeline logic is not implemented yet. Routes under `/api/v1` return placeholder JSON except `/api/v1/health` and in-memory `/api/v1/sites` CRUD.

## Prerequisites

- Python 3.11+
- A copy of the repo-root `.env.example` saved as `.env` (backend also reads `backend/.env`)

## Run locally

From `backend/`:

```bash
python -m venv venv
```

Windows:

```powershell
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

macOS / Linux:

```bash
source venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

- API: http://127.0.0.1:8000
- Docs: http://127.0.0.1:8000/docs
- Health: http://127.0.0.1:8000/api/v1/health → `{"status":"ok"}`

CORS origins come from `BACKEND_CORS_ORIGINS` (comma-separated). Default allows the Schach/phpChess frontend on `http://localhost:8080`.

## Tests

```bash
pytest
```

## Docker

```bash
docker build -t wind-suitability-api .
docker run --rm -p 8000:8000 --env-file ../.env wind-suitability-api
```

## Layout

- `app/api/routes/` — HTTP endpoints
- `app/services/` — pipeline stages (later)
- `app/ml/` — Random Forest (later)
- `app/gis/` — raster/vector helpers (later)
- `app/db/` — SQLite session (swap `DATABASE_URL` for PostGIS later)
- `data/raw`, `data/processed`, `data/outputs` — GIS artifacts
