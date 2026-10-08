"""Artist-side demo state applied after every reset.

Halcyon's rider is already on file and approved, so the shared Moog is reserved
for 18:00 to 19:15 on Saturday. Neon Tide's rider then triggers problem 2.
"""

from __future__ import annotations

from backend.app import db
from backend.app.artists import tickets
from backend.app.artists._compat import now

HALCYON_ID = 2
HALCYON_RIDER = "data/docs/riders/halcyon_rider.pdf"


def after_reset() -> None:
    with db.get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO documents (owner_type, owner_id, kind, filename, path, received_at)
               VALUES ('artist', ?, 'rider', 'halcyon_rider.pdf', ?, ?)""",
            (HALCYON_ID, HALCYON_RIDER, now()),
        )
        doc_id = int(cur.lastrowid)
    ticket_id = tickets.process_rider(HALCYON_ID, [doc_id])
    tickets.approve_rider(ticket_id, "jess")
    with db.get_conn() as conn:
        conn.execute("UPDATE tickets SET decided_by = 'jess', decided_at = ? WHERE id = ?", (now(), ticket_id))
        conn.execute("DELETE FROM notifications")
