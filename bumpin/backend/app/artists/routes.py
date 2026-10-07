"""Backend A routes: /overview, /artists, /inventory, /runsheet, /export, /documents, /demo/reset."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.app import db
from backend.app.deps import current_user

router = APIRouter()


@router.post("/demo/reset")
def demo_reset(user: str = Depends(current_user)) -> dict:
    counts = db.reset()
    return {"ok": True, "sim_today": db.SIM_TODAY, "counts": counts, "by": user}


@router.get("/artists")
def list_artists() -> list[dict]:
    with db.get_conn() as conn:
        return db.rows(conn.execute(
            """SELECT a.*, s.name AS stage_name FROM artists a
               LEFT JOIN stages s ON s.id = a.stage_id
               ORDER BY a.set_start, a.name"""
        ))


@router.get("/inventory")
def list_inventory() -> list[dict]:
    with db.get_conn() as conn:
        return db.rows(conn.execute(
            """SELECT i.*, s.name AS stage_name FROM inventory_items i
               LEFT JOIN stages s ON s.id = i.stage_id
               ORDER BY i.stage_id IS NULL, i.stage_id, i.canonical_name"""
        ))
