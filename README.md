# Backend

FastAPI + SQLAlchemy 2 async + PostgreSQL.

## Desarrollo rápido

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
python -m app.scripts.bootstrap
uvicorn app.main:app --reload --port 8000
```

PowerShell usa `.\\.venv\\Scripts\\Activate.ps1` y `Copy-Item .env.example .env`.

Worker:

```bash
arq app.workers.outbox_worker.WorkerSettings
```

Swagger: `http://localhost:8000/docs`.
