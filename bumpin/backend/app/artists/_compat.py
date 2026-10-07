"""Use Backend B's shared modules when present, local stand-ins otherwise.

The stand-ins follow the contract signatures (section 6) so nothing here
needs to change when the real modules land.
"""

from __future__ import annotations

import json
from datetime import datetime

from backend.app import db


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def audit(conn, ticket_id: int | None, actor: str, action: str, detail: str | dict = "") -> None:
    if isinstance(detail, dict):
        detail = json.dumps(detail)
    conn.execute(
        "INSERT INTO audit_log (ticket_id, actor, action, detail, at) VALUES (?, ?, ?, ?, ?)",
        (ticket_id, actor, action, detail, now()),
    )


# --- decisions -------------------------------------------------------------

try:
    from backend.app.shared.decisions import AlreadyDecided, decide  # type: ignore
except ImportError:
    FINAL_ACTIONS = {"approve", "reject"}

    class AlreadyDecided(Exception):
        def __init__(self, by: str, at: str):
            super().__init__(f"Already decided by {by} at {at}")
            self.by = by
            self.at = at

    def decide(ticket_id: int, actor: str, action: str, payload: dict | None = None):
        """First approve or reject wins. Other actions are only audited."""
        with db.get_conn() as conn:
            t = db.row(conn.execute("SELECT decided_by, decided_at FROM tickets WHERE id = ?", (ticket_id,)))
            if t is None:
                raise KeyError(ticket_id)
            if action in FINAL_ACTIONS:
                if t["decided_by"]:
                    raise AlreadyDecided(t["decided_by"], t["decided_at"])
                conn.execute(
                    "UPDATE tickets SET decided_by = ?, decided_at = ?, updated_at = ? WHERE id = ?",
                    (actor, now(), now(), ticket_id),
                )
            audit(conn, ticket_id, actor, action, payload or {})
        return {"ticket_id": ticket_id, "actor": actor, "action": action}


# --- outbox ----------------------------------------------------------------

try:
    from backend.app.shared.outbox import draft_email  # type: ignore
except ImportError:
    def draft_email(ticket_id: int, to_addr: str, intent: str, facts: dict) -> int:
        """Stand-in: stores the templated subject and body from facts as a draft."""
        with db.get_conn() as conn:
            cur = conn.execute(
                """INSERT INTO outbox (ticket_id, to_addr, subject, body, context_used_json,
                                       status, created_by, mode)
                   VALUES (?, ?, ?, ?, ?, 'draft', ?, 'mock')""",
                (
                    ticket_id,
                    to_addr,
                    facts.get("subject", intent),
                    facts.get("body", ""),
                    json.dumps(facts.get("context_used", [])),
                    facts.get("actor", "system"),
                ),
            )
            return int(cur.lastrowid)


# --- notifications ---------------------------------------------------------

try:
    from backend.app.shared.notifications import notify  # type: ignore
except ImportError:
    def notify(for_user: str, ticket_id: int, text: str) -> None:
        with db.get_conn() as conn:
            conn.execute(
                "INSERT INTO notifications (for_user, ticket_id, text, created_at, seen) VALUES (?, ?, ?, ?, 0)",
                (for_user, ticket_id, text, now()),
            )


# --- handler registry ------------------------------------------------------

try:
    from backend.app.shared.registry import register_handler  # type: ignore
except ImportError:
    LOCAL_HANDLERS: dict[str, object] = {}

    def register_handler(ticket_type: str, handler) -> None:
        LOCAL_HANDLERS[ticket_type] = handler


def other_user(actor: str) -> str:
    return "jess" if actor == "ravi" else "ravi"
