"""Generic ticket router. Dispatches to the handler registered for the ticket type."""

from __future__ import annotations

import json

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import JSONResponse

from backend.app import artists, db  # importing artists registers rider_needs and help
from backend.app import vendors  # noqa: F401  registers vendor_eligibility
from backend.app.deps import current_user
from backend.app.shared.decisions import AlreadyDecided
from backend.app.shared.registry import get_handler

router = APIRouter(tags=["tickets"])


# --- reads ---------------------------------------------------------------------------------

def owner_of(conn, ticket: dict) -> dict | None:
    table = {"artist": "artists", "vendor": "vendors"}.get(ticket["owner_type"] or "")
    if not table or ticket["owner_id"] is None:
        return None
    r = conn.execute(f"SELECT name FROM {table} WHERE id = ?", (ticket["owner_id"],)).fetchone()
    return {"type": ticket["owner_type"], "id": ticket["owner_id"], "name": r[0] if r else None}


def _documents(conn, ticket: dict, findings: list[dict]) -> list[dict]:
    ids: list[int] = []
    if ticket["owner_id"] is not None:
        ids += [r[0] for r in conn.execute(
            "SELECT id FROM documents WHERE owner_type = ? AND owner_id = ? ORDER BY id",
            (ticket["owner_type"], ticket["owner_id"]))]
    ids += [r[0] for r in conn.execute(
        "SELECT d.id FROM documents d JOIN emails e ON e.id = d.email_id WHERE e.ticket_id = ?", (ticket["id"],))]
    ids += [f["doc_id"] for f in findings if f["doc_id"]]
    out = []
    for doc_id in dict.fromkeys(ids):
        d = db.row(conn.execute(
            "SELECT id, kind, filename, expiry_date, issuer FROM documents WHERE id = ?", (doc_id,)))
        if d:
            out.append(d)
    return out


def ticket_detail(ticket_id: int) -> dict:
    with db.get_conn() as conn:
        t = db.row(conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)))
        if t is None:
            raise KeyError(f"ticket {ticket_id} not found")
        findings = db.rows(conn.execute("SELECT * FROM findings WHERE ticket_id = ? ORDER BY id", (ticket_id,)))
        for f in findings:
            f["bbox"] = json.loads(f.pop("bbox_json")) if f["bbox_json"] else None
        ob = db.row(conn.execute("SELECT * FROM outbox WHERE ticket_id = ? ORDER BY id DESC LIMIT 1", (ticket_id,)))
        draft = None
        if ob:
            draft = {"outbox_id": ob["id"], "to": ob["to_addr"], "subject": ob["subject"], "body": ob["body"],
                     "context_used": json.loads(ob["context_used_json"] or "[]"), "status": ob["status"]}
        return {
            "id": t["id"],
            "type": t["type"],
            "status": t["status"],
            "severity": t["severity"],
            "owner": owner_of(conn, t),
            "summary": t["summary"],
            "findings": findings,
            "documents": _documents(conn, t, findings),
            "proposed_actions": json.loads(t["proposed_actions_json"]) if t["proposed_actions_json"] else [],
            "draft_email": draft,
            "decided_by": t["decided_by"],
            "decided_at": t["decided_at"],
            "created_at": t["created_at"],
            "updated_at": t["updated_at"],
        }


@router.get("/tickets")
def list_tickets(type: str | None = None, status: str | None = None) -> list[dict]:
    sql, args = "SELECT * FROM tickets WHERE 1=1", []
    if type:
        sql += " AND type = ?"
        args.append(type)
    if status:
        sql += " AND status = ?"
        args.append(status)
    with db.get_conn() as conn:
        out = []
        for t in db.rows(conn.execute(sql + " ORDER BY updated_at DESC, id DESC", args)):
            t.pop("proposed_actions_json", None)
            t["owner"] = owner_of(conn, t)
            t["open_findings"] = conn.execute(
                "SELECT COUNT(*) FROM findings WHERE ticket_id = ? AND status = 'open'", (t["id"],)).fetchone()[0]
            out.append(t)
    return out


@router.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: int) -> dict:
    try:
        return ticket_detail(ticket_id)
    except KeyError as e:
        raise HTTPException(404, str(e.args[0]))


# --- actions --------------------------------------------------------------------------------

def _act(ticket_id: int, call):
    """Look up the handler for the ticket, run call(handler), return the fresh ticket.

    409 for AlreadyDecided carries {decided_by, decided_at} at the top level so
    the phone and laptop UIs can show who decided."""
    try:
        with db.get_conn() as conn:
            t = db.row(conn.execute("SELECT type FROM tickets WHERE id = ?", (ticket_id,)))
        if t is None:
            raise KeyError(f"ticket {ticket_id} not found")
        call(get_handler(t["type"]))
        return ticket_detail(ticket_id)
    except AlreadyDecided as e:
        return JSONResponse(status_code=409, content={
            "decided_by": e.by, "decided_at": e.at, "detail": str(e)})
    except artists.RiderBlocked as e:
        return JSONResponse(status_code=409, content={"detail": str(e)})
    except KeyError as e:
        return JSONResponse(status_code=404, content={"detail": str(e.args[0]) if e.args else "not found"})
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})


@router.post("/tickets/{ticket_id}/findings/{finding_id}/ignore")
def ignore_finding(ticket_id: int, finding_id: int, user: str = Depends(current_user)):
    return _act(ticket_id, lambda h: h.ignore_finding(ticket_id, finding_id, user))


@router.post("/tickets/{ticket_id}/findings/{finding_id}/resolve")
def resolve_finding(ticket_id: int, finding_id: int, user: str = Depends(current_user)):
    return _act(ticket_id, lambda h: h.resolve_finding(ticket_id, finding_id, user))


@router.post("/tickets/{ticket_id}/approve")
def approve(ticket_id: int, payload: dict | None = Body(default=None), user: str = Depends(current_user)):
    return _act(ticket_id, lambda h: h.approve(ticket_id, user, payload))


@router.post("/tickets/{ticket_id}/reject")
def reject(ticket_id: int, payload: dict | None = Body(default=None), user: str = Depends(current_user)):
    body = payload or {}
    reason = (body.get("reason") or body.get("override_reason") or "").strip()
    return _act(ticket_id, lambda h: h.reject(ticket_id, user, reason))


@router.post("/tickets/{ticket_id}/actions/{index}/approve")
def approve_action(ticket_id: int, index: int, user: str = Depends(current_user)):
    return _act(ticket_id, lambda h: h.approve_action(ticket_id, index, user))


@router.post("/tickets/{ticket_id}/actions/{index}/edit")
def edit_action(ticket_id: int, index: int, edits: dict = Body(default_factory=dict),
                user: str = Depends(current_user)):
    return _act(ticket_id, lambda h: h.edit_action(ticket_id, index, user, edits))
