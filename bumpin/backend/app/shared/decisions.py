"""First decision wins (contract section 11).

Only "approve" and "reject" lock a ticket. Every other action (resolve_finding,
ignore_finding, approve_action, edit_action) is written to the audit log only,
so it never blocks the later approve.
"""

from __future__ import annotations

import json
from datetime import datetime

from pydantic import BaseModel

from backend.app import db

FINAL_ACTIONS = {"approve", "reject"}


class AlreadyDecided(Exception):
    def __init__(self, by: str, at: str):
        super().__init__(f"Already decided by {by} at {at}")
        self.by = by
        self.at = at


class Decision(BaseModel):
    ticket_id: int
    actor: str
    action: str
    at: str


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def audit(conn, ticket_id: int | None, actor: str, action: str, detail: str | dict | None = "") -> None:
    if not isinstance(detail, str):
        detail = json.dumps(detail or {})
    conn.execute(
        "INSERT INTO audit_log (ticket_id, actor, action, detail, at) VALUES (?, ?, ?, ?, ?)",
        (ticket_id, actor, action, detail, now()),
    )


def decide(ticket_id: int, actor: str, action: str, payload: dict | None = None) -> Decision:
    """Record an action. Raises KeyError for an unknown ticket and AlreadyDecided
    when an approve or reject arrives after the ticket was already decided."""
    at = now()
    with db.get_conn() as conn:
        t = db.row(conn.execute("SELECT decided_by, decided_at FROM tickets WHERE id = ?", (ticket_id,)))
        if t is None:
            raise KeyError(f"ticket {ticket_id} not found")
        if action in FINAL_ACTIONS:
            # The WHERE clause makes the claim atomic if two requests race.
            cur = conn.execute(
                "UPDATE tickets SET decided_by = ?, decided_at = ?, updated_at = ? "
                "WHERE id = ? AND decided_by IS NULL",
                (actor, at, at, ticket_id),
            )
            if cur.rowcount == 0:
                t = db.row(conn.execute("SELECT decided_by, decided_at FROM tickets WHERE id = ?", (ticket_id,)))
                raise AlreadyDecided(t["decided_by"], t["decided_at"])
        audit(conn, ticket_id, actor, action, payload)
    return Decision(ticket_id=ticket_id, actor=actor, action=action, at=at)
