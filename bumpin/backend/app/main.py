"""BumpIn FastAPI app. Run from the bumpin/ folder:

    uvicorn backend.app.main:app --reload

Hosted demo (Dockerfile at the repo root): set BUMPIN_PUBLIC_DEMO=1. The app then
restores the demo baseline on startup and again every DEMO_RESET_MINUTES (default
30), because every click a visitor makes is a real write. If frontend/dist exists
it is served from the same address, so one service is the whole product.
"""

from __future__ import annotations

import logging
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from backend.app import db
from backend.app.artists.routes import demo_reset
from backend.app.artists.routes import router as artists_router
from backend.app.shared import mailbox
from backend.app.shared.router_registry import ROUTERS


log = logging.getLogger("bumpin")

PUBLIC_DEMO = os.getenv("BUMPIN_PUBLIC_DEMO") == "1"
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def _reset_loop(stop: threading.Event, minutes: float) -> None:
    while not stop.wait(minutes * 60):
        try:
            demo_reset(user="auto-reset")
        except Exception:  # a failed reset must not kill the loop
            log.exception("scheduled demo reset failed")


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.ensure_ready()
    stop = threading.Event()
    if PUBLIC_DEMO:
        demo_reset(user="startup")
        minutes = float(os.getenv("DEMO_RESET_MINUTES") or 30)
        threading.Thread(target=_reset_loop, args=(stop, minutes), daemon=True).start()
    mailbox.start()  # polls a real inbox when IMAP_USER and IMAP_PASSWORD are set
    yield
    stop.set()


app = FastAPI(title="BumpIn", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "festival": db.festival().get("name")}


app.include_router(artists_router, prefix="/api")
for r in ROUTERS:
    app.include_router(r, prefix="/api")


if FRONTEND_DIST.is_dir():
    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str) -> FileResponse:
        """The built React app. Real files are served as-is; any other path is a
        client-side route, so it gets index.html."""
        if path.startswith("api/"):
            raise HTTPException(status_code=404)
        file = (FRONTEND_DIST / path).resolve()
        if path and file.is_file() and FRONTEND_DIST in file.parents:
            return FileResponse(file)
        return FileResponse(FRONTEND_DIST / "index.html")
