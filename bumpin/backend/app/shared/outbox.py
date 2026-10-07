"""Drafted emails. Nothing here sends by itself: send() runs only when a human calls it.

EMAIL_MODE=mock  marks the row sent, no network.
EMAIL_MODE=demo  also delivers to DEMO_RECIPIENT only, never to the real address.
"""

from __future__ import annotations

import json
import os
import smtplib
from email.message import EmailMessage

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.app import db
from backend.app.deps import current_user
from backend.app.shared.decisions import audit, now
from backend.app.shared.notifications import notify

POLICY = "email_policy.md"
SIGN_OFF = "Kind regards,\nThe Riverside Festival Team"

router = APIRouter(tags=["outbox"])


def clean_text(text: str) -> str:
    """No em dashes or en dashes in any outbound or user-facing text."""
    return (text or "").replace(" — ", ", ").replace("—", ", ").replace("–", "-")


def _email_mode() -> str:
    return os.getenv("EMAIL_MODE", "mock").strip().lower() or "mock"


def draft_email(ticket_id: int | None, to_addr: str, intent: str, facts: dict) -> int:
    """Store a draft and return its outbox id. Uses facts["subject"] and facts["body"] when
    given, otherwise a plain template built from the intent. context_used always lists
    email_policy.md."""
    subject = facts.get("subject") or intent.replace("_", " ").capitalize()
    body = facts.get("body") or (
        f"Hi,\n\n{facts.get('message') or intent.replace('_', ' ').capitalize()}.\n\n"
        f"Let us know if you have any questions.\n\n{SIGN_OFF}"
    )
    context = list(facts.get("context_used") or [])
    if POLICY not in context:
        context.append(POLICY)
    actor = facts.get("actor", "system")
    with db.get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO outbox (ticket_id, to_addr, subject, body, context_used_json,
                                   status, created_by, mode)
               VALUES (?, ?, ?, ?, ?, 'draft', ?, ?)""",
            (ticket_id, to_addr, clean_text(subject), clean_text(body), json.dumps(context),
             actor, _email_mode()),
        )
        oid = int(cur.lastrowid)
        audit(conn, ticket_id, actor, "email_drafted", {"outbox_id": oid, "to": to_addr})
    return oid


def _get(conn, outbox_id: int) -> dict:
    o = db.row(conn.execute("SELECT * FROM outbox WHERE id = ?", (outbox_id,)))
    if o is None:
        raise KeyError(f"outbox {outbox_id} not found")
    return o


def update_draft(outbox_id: int, subject: str | None, body: str | None) -> None:
    with db.get_conn() as conn:
        o = _get(conn, outbox_id)
        if o["status"] != "draft":
            raise ValueError("Only drafts can be edited.")
        conn.execute(
            "UPDATE outbox SET subject = ?, body = ? WHERE id = ?",
            (clean_text(subject) if subject is not None else o["subject"],
             clean_text(body) if body is not None else o["body"], outbox_id),
        )


def _smtp_deliver(to_addr: str, subject: str, body: str) -> None:
    host = os.getenv("SMTP_HOST", "")
    if not host:
        raise ValueError("EMAIL_MODE=demo needs SMTP_HOST set.")
    msg = EmailMessage()
    msg["From"] = os.getenv("SMTP_USER") or "bumpin@fieldday.example.test"
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(host, int(os.getenv("SMTP_PORT") or 587), timeout=15) as s:
        s.starttls()
        if os.getenv("SMTP_USER"):
            s.login(os.getenv("SMTP_USER", ""), os.getenv("SMTP_PASS", ""))
        s.send_message(msg)


def send(outbox_id: int, actor: str) -> None:
    mode = _email_mode()
    with db.get_conn() as conn:
        o = _get(conn, outbox_id)
    if o["status"] == "sent":
        raise ValueError("This email was already sent.")

    delivered_to = o["to_addr"]
    if mode == "demo":
        # Never the artist or vendor address.
        delivered_to = os.getenv("DEMO_RECIPIENT", "").strip()
        if not delivered_to:
            raise ValueError("EMAIL_MODE=demo needs DEMO_RECIPIENT set.")
        try:
            _smtp_deliver(
                delivered_to,
                o["subject"],
                f"[Demo delivery. Intended for {o['to_addr']}]\n\n{o['body']}",
            )
        except Exception as e:
            with db.get_conn() as conn:
                conn.execute("UPDATE outbox SET status = 'failed', mode = ? WHERE id = ?", (mode, outbox_id))
                audit(conn, o["ticket_id"], actor, "email_failed", {"outbox_id": outbox_id, "error": str(e)})
            raise

    with db.get_conn() as conn:
        conn.execute(
            "UPDATE outbox SET status = 'sent', approved_by = ?, sent_at = ?, mode = ? WHERE id = ?",
            (actor, now(), mode, outbox_id),
        )
        conn.execute(
            """INSERT INTO emails (direction, from_addr, to_addr, subject, body, received_at, ticket_id)
               VALUES ('out', 'bumpin@fieldday.example.test', ?, ?, ?, ?, ?)""",
            (o["to_addr"], o["subject"], o["body"], now(), o["ticket_id"]),
        )
        audit(conn, o["ticket_id"], actor, "email_sent",
              {"outbox_id": outbox_id, "to": o["to_addr"], "mode": mode, "delivered_to": delivered_to})
    if o["ticket_id"]:
        notify("jess" if actor == "ravi" else "ravi", o["ticket_id"],
               f"{actor.title()} sent an email to {o['to_addr']}: {o['subject']}")


# --- API ---------------------------------------------------------------------------------

def _present(o: dict) -> dict:
    o = dict(o)
    o["context_used"] = json.loads(o.pop("context_used_json") or "[]")
    return o


class DraftPatch(BaseModel):
    subject: str | None = None
    body: str | None = None


@router.get("/outbox")
def list_outbox(status: str | None = None, ticket_id: int | None = None) -> list[dict]:
    sql, args = "SELECT * FROM outbox WHERE 1=1", []
    if status:
        sql += " AND status = ?"
        args.append(status)
    if ticket_id is not None:
        sql += " AND ticket_id = ?"
        args.append(ticket_id)
    with db.get_conn() as conn:
        return [_present(o) for o in db.rows(conn.execute(sql + " ORDER BY id DESC", args))]


@router.patch("/outbox/{outbox_id}")
def patch_outbox(outbox_id: int, patch: DraftPatch) -> dict:
    try:
        update_draft(outbox_id, patch.subject, patch.body)
        with db.get_conn() as conn:
            return _present(_get(conn, outbox_id))
    except KeyError as e:
        raise HTTPException(404, str(e.args[0]))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/outbox/{outbox_id}/send")
def send_outbox(outbox_id: int, user: str = Depends(current_user)) -> dict:
    try:
        send(outbox_id, user)
        with db.get_conn() as conn:
            return _present(_get(conn, outbox_id))
    except KeyError as e:
        raise HTTPException(404, str(e.args[0]))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"Delivery failed: {e}")
