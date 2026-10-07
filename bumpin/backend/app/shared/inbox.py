"""Inbox pipeline: POST /api/inbox/receive.

Store the email and attachments, extract text, classify, route by label and sender
role, then apply the routing policy from contract section 5. Everything that
decides (dates, bands, critical fields) is plain code.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.app import artists, db, vendors
from backend.app.shared.classifier import Classification, classify
from backend.app.shared.decisions import audit, now
from backend.app.shared.llm import extract_text
from backend.app.shared.notifications import notify

router = APIRouter(tags=["inbox"])

ROOT = db.ROOT
AUTO_FILE = 0.90
TOP_OF_LIST = 0.60
MAJOR_WINDOW_DAYS = 14
MAX_CLASSIFY_CHARS = 6000


class InboundEmail(BaseModel):
    from_: str = Field(alias="from")
    subject: str = ""
    body: str = ""
    attachments: list[str] = []

    model_config = {"populate_by_name": True}


# --- helpers ---------------------------------------------------------------------------------

def sender_role(from_addr: str) -> tuple[str, dict | None]:
    """Who is writing, from the address book. Code, not an LLM guess."""
    with db.get_conn() as conn:
        a = db.row(conn.execute("SELECT * FROM artists WHERE lower(manager_email) = lower(?)", (from_addr,)))
        if a:
            return "artist", a
        v = db.row(conn.execute("SELECT * FROM vendors WHERE lower(contact_email) = lower(?)", (from_addr,)))
        if v:
            return "vendor", v
    return "unknown", None


def within_major_window() -> bool:
    fest = db.festival()
    if not fest:
        return False
    days = (date.fromisoformat(fest["start_date"]) - date.fromisoformat(fest["sim_today"])).days
    return days <= MAJOR_WINDOW_DAYS


def _store_email(msg: InboundEmail) -> tuple[int, list[tuple[int, str]]]:
    """Insert the email and one documents row per attachment, with text extracted."""
    stored: list[tuple[int, str]] = []
    with db.get_conn() as conn:
        email_id = conn.execute(
            "INSERT INTO emails (direction, from_addr, subject, body, received_at) VALUES ('in', ?, ?, ?, ?)",
            (msg.from_, msg.subject, msg.body, now()),
        ).lastrowid
        for rel in msg.attachments:
            path = ROOT / rel
            if not path.exists():
                raise ValueError(f"attachment not found: {rel}")
            pages = extract_text(str(path))
            text = "\n".join(p.text for p in pages)
            doc_id = conn.execute(
                """INSERT INTO documents (owner_type, owner_id, kind, filename, path, extracted_text,
                                          received_at, email_id)
                   VALUES ('artist', 0, 'other', ?, ?, ?, ?, ?)""",
                (Path(rel).name, rel, text, now(), email_id),
            ).lastrowid
            stored.append((doc_id, text))
    return email_id, stored


def _classification_text(msg: InboundEmail, docs: list[tuple[int, str]]) -> str:
    parts = [f"From: {msg.from_}", f"Subject: {msg.subject}", "", msg.body]
    for rel, (_, text) in zip(msg.attachments, docs):
        parts += ["", f"[attachment {Path(rel).name}]", text.strip()]
    return "\n".join(parts)[:MAX_CLASSIFY_CHARS]


def _review_ticket(email_id: int, msg: InboundEmail, role: str, owner: dict | None, cls: Classification) -> int:
    """Catch-all needs_review ticket (type help, no proposed actions) for unclear mail."""
    owner_type = role if role in ("artist", "vendor") else None
    who = owner["name"] if owner else msg.from_
    snippet = " ".join(msg.body.split())[:200]
    with db.get_conn() as conn:
        tid = conn.execute(
            """INSERT INTO tickets (type, owner_type, owner_id, status, severity, summary, created_at, updated_at)
               VALUES ('help', ?, ?, 'needs_review', 'warning', ?, ?, ?)""",
            (owner_type, owner["id"] if owner else None,
             f"{who}: unclear email, needs a human ({cls.confidence:.2f}).", now(), now()),
        ).lastrowid
        conn.execute(
            """INSERT INTO findings (ticket_id, kind, severity, message, suggestion, quote, status)
               VALUES (?, 'low_confidence', 'warning', ?, ?, ?, 'open')""",
            (tid, f"BumpIn could not tell what this email is. {cls.reason}",
             "Read it and file it by hand, or reply to ask what they need.", snippet),
        )
        conn.execute("UPDATE emails SET ticket_id = ? WHERE id = ?", (tid, email_id))
        audit(conn, tid, "system", "ticket_created", {"type": "help", "unsure": True})
    return tid


def _route(email_id: int, msg: InboundEmail, role: str, owner: dict | None, cls: Classification) -> int:
    if cls.label == "rider" and role != "vendor":
        return artists.create_rider_ticket(email_id, cls)
    if cls.label == "vendor_doc" and role != "artist":
        return vendors.create_vendor_ticket(email_id, cls)
    if cls.label == "help_or_change" and role == "artist":
        return artists.create_help_ticket(email_id, cls)
    if cls.label == "help_or_change" and role == "vendor":
        return vendors.create_vendor_change_ticket(email_id, cls)
    return _review_ticket(email_id, msg, role, owner, cls)


def _apply_policy(ticket_id: int, cls: Classification) -> str:
    """Confidence bands. Below 0.90 the ticket goes to review, with a finding saying why."""
    with db.get_conn() as conn:
        t = db.row(conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)))
        if cls.confidence >= AUTO_FILE or t["status"] in ("approved", "rejected", "resolved"):
            return t["status"]
        has_flag = conn.execute(
            "SELECT COUNT(*) FROM findings WHERE ticket_id = ? AND kind = 'low_confidence' AND status = 'open'",
            (ticket_id,)).fetchone()[0]
        if not has_flag:
            conn.execute(
                """INSERT INTO findings (ticket_id, kind, severity, message, suggestion, status)
                   VALUES (?, 'low_confidence', 'warning', ?, ?, 'open')""",
                (ticket_id, f"Classified with low confidence ({cls.confidence:.2f}). {cls.reason}",
                 "Confirm what this email is before acting on it."),
            )
        conn.execute("UPDATE tickets SET status = 'needs_review', updated_at = ? WHERE id = ?", (now(), ticket_id))
    return "needs_review"


# --- pipeline ---------------------------------------------------------------------------------

def receive(msg: InboundEmail) -> dict:
    email_id, docs = _store_email(msg)
    role, owner = sender_role(msg.from_)

    cls = classify(_classification_text(msg, docs))
    # The address book beats the model on who the sender is.
    if role != "unknown":
        cls = cls.model_copy(update={"sender_role": role})
    if owner and not cls.entity_hint:
        cls = cls.model_copy(update={"entity_hint": owner["name"]})

    with db.get_conn() as conn:
        conn.execute(
            "UPDATE emails SET classification = ?, confidence = ?, is_major_change = ? WHERE id = ?",
            (cls.label, cls.confidence, int(cls.is_major_change), email_id),
        )

    ticket_id = _route(email_id, msg, role, owner, cls)
    status = _apply_policy(ticket_id, cls)

    with db.get_conn() as conn:
        flagged = conn.execute("SELECT is_major_change FROM emails WHERE id = ?", (email_id,)).fetchone()[0]
        major = bool(cls.is_major_change or flagged)  # a ticket creator may also flag a major change
        conn.execute("UPDATE emails SET ticket_id = ?, classification = ?, confidence = ?, is_major_change = ? "
                     "WHERE id = ?", (ticket_id, cls.label, cls.confidence, int(major), email_id))
        ticket = db.row(conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)))
        audit(conn, ticket_id, "system", "email_routed",
              {"email_id": email_id, "label": cls.label, "confidence": cls.confidence, "role": role})

    notified = False
    if major and within_major_window():
        notify("ravi", ticket_id, f"Major change: {ticket['summary']}")
        notified = True

    band = ("auto" if cls.confidence >= AUTO_FILE else "review" if cls.confidence >= TOP_OF_LIST else "review_top")
    return {
        "email_id": email_id,
        "ticket_id": ticket_id,
        "ticket_type": ticket["type"],
        "ticket_status": status,
        "routing": "auto_filed" if status in ("open", "in_progress") else "needs_review",
        "confidence_band": band,
        "notified_ravi": notified,
        "is_major_change": major,
        "classification": cls.model_dump(),
    }


@router.post("/inbox/receive")
def inbox_receive(msg: InboundEmail):
    try:
        return receive(msg)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})
