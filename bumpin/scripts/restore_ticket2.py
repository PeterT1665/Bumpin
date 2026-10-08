"""Put ticket 2 back to the baseline HANDOFF.md documents.

Verifying the resolve flow has to actually resolve something, and ticket 2 holds
the only open rider finding in the demo — so proving the flow works consumes the
one case that demonstrates it. After the test there was no open rider finding
left anywhere, which makes both the hover card and the Resolve button
unreachable on every rider ticket.

This rewinds exactly that one test: ticket 2's shortage finding back to `open`,
ticket 2 back to `needs_review`, the drafted reply removed from the outbox, and
the two audit rows the resolve wrote dropped so the log does not claim a resolve
that no longer shows. Nothing else is touched.

The finding is looked up by (ticket 2, kind `shortage`) rather than by its id.
`process_rider` deletes and rewrites every rider finding on each ingest, so the
id this script used to hardcode (5) stopped existing the first time
`ingest_initial` ran and the rewind silently did nothing.
"""
import sqlite3
import pathlib

DB = pathlib.Path(__file__).resolve().parent.parent / "data" / "bumpin.db"

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row


#: Ticket 2 is Sparkle's rider and its conflict is the CDJ-3000 shortage on the
#: photographed page. One row, so the lookup is unambiguous.
FINDING = conn.execute(
    "SELECT id FROM findings WHERE ticket_id = 2 AND kind = 'shortage'").fetchall()
if len(FINDING) != 1:
    raise SystemExit(f"expected exactly one shortage finding on ticket 2, found {len(FINDING)}")
FINDING_ID = FINDING[0][0]


def show(tag):
    f = conn.execute("SELECT status FROM findings WHERE id = ?", (FINDING_ID,)).fetchone()
    t = conn.execute("SELECT status FROM tickets WHERE id = 2").fetchone()
    n = conn.execute("SELECT COUNT(*) FROM outbox WHERE ticket_id = 2").fetchone()[0]
    print(f"{tag:<8} finding {FINDING_ID}: {f['status']:<9} ticket 2: {t['status']:<13} outbox rows: {n}")


show("before")
conn.execute("UPDATE findings SET status = 'open' WHERE id = ?", (FINDING_ID,))
conn.execute("UPDATE tickets SET status = 'needs_review' WHERE id = 2")
conn.execute("DELETE FROM outbox WHERE ticket_id = 2 AND status = 'draft'")
conn.execute("DELETE FROM audit_log WHERE ticket_id = 2 AND actor = 'ravi'")
conn.commit()
show("after")
conn.close()
