"""Backend A routes: /overview, /artists, /inventory, /runsheet, /export, /documents, /demo/reset."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse, Response

from backend.app import db
from backend.app.artists import demo, riders
from backend.app.artists.runsheet import build_runsheet, runsheet_xlsx
from backend.app.deps import current_user

router = APIRouter()

if demo.after_reset not in db.POST_RESET_HOOKS:
    db.POST_RESET_HOOKS.insert(0, demo.after_reset)


@router.post("/demo/reset")
def demo_reset(user: str = Depends(current_user)) -> dict:
    counts = db.reset()
    return {"ok": True, "sim_today": db.SIM_TODAY, "counts": counts, "by": user}


@router.get("/overview")
def overview() -> dict:
    with db.get_conn() as conn:
        fest = db.row(conn.execute("SELECT * FROM festival LIMIT 1")) or {}
        count = lambda sql, *a: conn.execute(sql, a).fetchone()[0]  # noqa: E731
        artists_total = count("SELECT COUNT(*) FROM artists")
        artists_scheduled = count("SELECT COUNT(*) FROM artists WHERE set_start IS NOT NULL")
        artists_ready = count("SELECT COUNT(*) FROM artists WHERE set_start IS NOT NULL AND status = 'completed'")
        vendors_total = count("SELECT COUNT(*) FROM vendors")
        vendors_ready = count("SELECT COUNT(*) FROM vendors WHERE status = 'completed'")
        return {
            "festival": fest,
            "suppliers": {
                "artists": artists_total, "artists_scheduled": artists_scheduled,
                "artists_applied": artists_total - artists_scheduled, "artists_ready": artists_ready,
                "vendors": vendors_total, "vendors_ready": vendors_ready,
            },
            "readiness_pct": round(100 * (artists_ready + vendors_ready) / max(artists_scheduled + vendors_total, 1)),
            "documents": count("SELECT COUNT(*) FROM documents"),
            "needing_attention": count("SELECT COUNT(*) FROM tickets WHERE status IN ('open', 'needs_review')"),
            "expiring_soon": count(
                "SELECT COUNT(*) FROM documents WHERE expiry_date IS NOT NULL AND expiry_date < ?",
                fest.get("end_date", "9999")),
            "open_conflicts": count("SELECT COUNT(*) FROM findings WHERE status = 'open' AND severity = 'conflict'"),
        }


@router.get("/artists")
def list_artists() -> list[dict]:
    with db.get_conn() as conn:
        return db.rows(conn.execute(
            """SELECT a.*, s.name AS stage_name,
                      (SELECT t.id FROM tickets t WHERE t.owner_type = 'artist' AND t.owner_id = a.id
                       ORDER BY t.updated_at DESC LIMIT 1) AS latest_ticket_id
               FROM artists a LEFT JOIN stages s ON s.id = a.stage_id
               ORDER BY a.set_start IS NULL, a.set_start, a.name"""
        ))


@router.get("/inventory")
def list_inventory() -> list[dict]:
    with db.get_conn() as conn:
        items = db.rows(conn.execute(
            """SELECT i.*, s.name AS stage_name FROM inventory_items i
               LEFT JOIN stages s ON s.id = i.stage_id
               ORDER BY i.stage_id IS NULL, i.stage_id, i.canonical_name"""
        ))
        allocs = db.rows(conn.execute(
            """SELECT al.*, a.name AS artist_name FROM allocations al JOIN artists a ON a.id = al.artist_id
               WHERE al.status = 'reserved' ORDER BY al.start_ts"""
        ))
    for i in items:
        i["aliases"] = json.loads(i.pop("aliases_json") or "[]")
        i["allocations"] = [
            {k: a[k] for k in ("artist_id", "artist_name", "quantity", "start_ts", "end_ts")}
            for a in allocs if a["inventory_item_id"] == i["id"]
        ]
    return items


@router.get("/runsheet")
def runsheet() -> list[dict]:
    return [r.model_dump() for r in build_runsheet()]


@router.get("/export/runsheet.xlsx")
def export_runsheet() -> Response:
    return Response(
        runsheet_xlsx(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="riverside_runsheet.xlsx"'},
    )


def _document(doc_id: int) -> dict:
    with db.get_conn() as conn:
        doc = db.row(conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)))
    if doc is None:
        raise HTTPException(404, "Document not found")
    return doc


@router.get("/documents/{doc_id}/file", response_model=None)
def document_file(doc_id: int):
    doc = _document(doc_id)
    path = riders.resolve_path(doc["path"])
    if path is None:
        # Pasted riders have no file: serve the text.
        return PlainTextResponse(doc["extracted_text"] or "")
    return FileResponse(path, filename=doc["filename"],
                        content_disposition_type="inline")


@router.get("/documents/{doc_id}/highlights")
def document_highlights(doc_id: int) -> list[dict]:
    _document(doc_id)
    with db.get_conn() as conn:
        findings = db.rows(conn.execute(
            "SELECT id, severity, page, bbox_json FROM findings WHERE doc_id = ? AND status != 'ignored'",
            (doc_id,)))
    out = []
    for f in findings:
        box = json.loads(f["bbox_json"]) if f["bbox_json"] else {}
        for rect in box.get("rects", []):
            out.append({"page": box["page"], "rect": rect, "page_size": box["page_size"],
                        "finding_id": f["id"], "severity": f["severity"]})
    return out
