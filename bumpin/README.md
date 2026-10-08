# BumpIn: developer notes

**Trying the product?** Start with the [README at the repository root](../README.md). This page is for working on the code. See also `CLAUDE.md` and `docs/CONTRACT.md`.

**Demoing it?** Read [`DEMO.md`](DEMO.md) first — how to start both halves, what the walk-through is, which buttons write for real, and `./scripts/demo-reset` to put the data back between run-throughs.

## Run the backend

Needs Python 3.10 or newer. From this `bumpin/` folder:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env            # leave LLM_PROVIDER blank to run without AI
.venv/bin/uvicorn backend.app.main:app --reload
```

- Health check: `GET http://localhost:8000/api/health`
- Reset demo data: `POST http://localhost:8000/api/demo/reset` (restores `data/demo_baseline.db`, like `./scripts/demo-reset`)
- API docs: `http://localhost:8000/docs`
- Tests: `.venv/bin/python -m pytest -q`

The SQLite database is `data/bumpin.db`. It is built from `data/seed/<table>.json` on first start and on every reset. To seed a new table, drop a JSON list of rows into `data/seed/` named after the table.

## Adding routes (Backend B)

Append your `APIRouter` to `ROUTERS` in `backend/app/shared/router_registry.py`. `main.py` mounts every router there under `/api`. Use `backend.app.deps.current_user` for the `X-User` header and `backend.app.db.get_conn()` for database access.
