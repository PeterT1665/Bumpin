"""GET /api/phone/cards: Ravi's action cards, most urgent first (contract section 13).

A card is an undecided ticket. Reason is major_change (the source email was flagged),
needs_review (a human must look), or pending_approval (filed, waiting for a click).
"""

from __future__ import annotations

import json
import re

from fastapi import APIRouter

from backend.app import db
from backend.app.shared.tickets import owner_of

router = APIRouter(tags=["phone"])

REASON_RANK = {"major_change": 0, "needs_review": 1, "pending_approval": 2}
LOW_CONFIDENCE = 0.60
SEVERITY_RANK = {"conflict": 0, "warning": 1, "info": 2}
_PREFIX = re.compile(r"^\s*((re|fwd?)\s*:\s*|urgent\s*:\s*|subject\s*:\s*)+", re.I)


def _headline(subject: str | None, owner_name: str | None, fallback: str) -> str:
    text = _PREFIX.sub("", (subject or "").strip())
    if owner_name:
        text = re.sub(rf"^{re.escape(owner_name)}\s*[:,]?\s*", "", text, flags=re.I)
    text = text.strip()
    return text[:1].lower() + text[1:] if text else fallback


def _card(conn, t: dict) -> dict | None:
    email = db.row(conn.execute(
        "SELECT * FROM emails WHERE ticket_id = ? AND direction = 'in' ORDER BY id DESC LIMIT 1", (t["id"],)))
    owner = owner_of(conn, t)
    name = owner["name"] if owner else None
    open_findings = db.rows(conn.execute(
        "SELECT id, kind, severity, quote FROM findings WHERE ticket_id = ? AND status = 'open' ORDER BY id",
        (t["id"],)))
    confidence = email["confidence"] if email and email["confidence"] is not None else 1.0

    if email and email["is_major_change"]:
        reason = "major_change"
    elif t["status"] == "needs_review":
        reason = "needs_review"
    else:
        reason = "pending_approval"
    urgency = "high" if reason == "major_change" or confidence < LOW_CONFIDENCE else \
        "medium" if reason == "needs_review" else "low"

    snippet = " ".join((email["body"] if email else "").split())
    if not snippet and open_findings:
        snippet = open_findings[0]["quote"] or ""
    has_actions = bool(json.loads(t["proposed_actions_json"] or "[]"))
    title = f"{name}: {_headline(email['subject'] if email else None, name, t['type'].replace('_', ' '))}" \
        if name else _headline(email["subject"] if email else None, None, t["summary"] or "Needs a look")

    return {
        "id": f"t{t['id']}",
        "ticket_id": t["id"],
        "urgency": urgency,
        "reason": reason,
        "title": title,
        "summary": t["summary"],
        "snippet": snippet[:200],
        "actions": ["approve", "edit", "dismiss"] if has_actions else ["approve", "reject", "dismiss"],
        "finding_ids": [f["id"] for f in open_findings],
        "created_at": t["created_at"],
        "_sort": (REASON_RANK[reason], {"high": 0, "medium": 1, "low": 2}[urgency],
                  min((SEVERITY_RANK[f["severity"]] for f in open_findings), default=3)),
    }


@router.get("/phone/cards")
def phone_cards(user: str = "ravi") -> list[dict]:
    with db.get_conn() as conn:
        tickets = db.rows(conn.execute(
            """SELECT * FROM tickets WHERE decided_by IS NULL AND status IN ('open', 'needs_review', 'in_progress')
               ORDER BY created_at DESC, id DESC"""))
        cards = [c for t in tickets if (c := _card(conn, t))]
    # Urgency first (low confidence outranks an ordinary review), then reason, then worst finding, then newest.
    cards.sort(key=lambda c: (c["_sort"][1], c["_sort"][0], c["_sort"][2]))
    for c in cards:
        c.pop("_sort")
    return cards
