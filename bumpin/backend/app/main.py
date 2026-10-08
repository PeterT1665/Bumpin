"""BumpIn FastAPI app. Run from the bumpin/ folder:

    uvicorn backend.app.main:app --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app import db
from backend.app.artists.routes import router as artists_router
from backend.app.shared import mailbox
from backend.app.shared.router_registry import ROUTERS


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.ensure_ready()
    mailbox.start()  # polls a real inbox when IMAP_USER and IMAP_PASSWORD are set
    yield


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
