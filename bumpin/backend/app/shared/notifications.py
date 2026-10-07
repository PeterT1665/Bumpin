"""In-app notifications for Ravi and Jess."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.app import db
from backend.app.shared.decisions import now

router = APIRouter(tags=["notifications"])


def notify(for_user: str, ticket_id: int | None, text: str) -> None:
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO notifications (for_user, ticket_id, text, created_at, seen) VALUES (?, ?, ?, ?, 0)",
            (for_user, ticket_id, text, now()),
        )


@router.get("/notifications")
def list_notifications(user: str, unseen_only: bool = False) -> list[dict]:
    sql = "SELECT * FROM notifications WHERE for_user = ?"
    if unseen_only:
        sql += " AND seen = 0"
    with db.get_conn() as conn:
        out = db.rows(conn.execute(sql + " ORDER BY id DESC", (user.lower(),)))
    for n in out:
        n["seen"] = bool(n["seen"])
    return out


@router.post("/notifications/{notification_id}/seen")
def mark_seen(notification_id: int) -> dict:
    with db.get_conn() as conn:
        cur = conn.execute("UPDATE notifications SET seen = 1 WHERE id = ?", (notification_id,))
        if cur.rowcount == 0:
            raise HTTPException(404, f"notification {notification_id} not found")
    return {"id": notification_id, "seen": True}
