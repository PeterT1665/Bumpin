"""Walk through the artist-side planted problems (1, 2, 3, 6) and print what happens.

Run from bumpin/:  .venv/bin/python scripts/demo_artists.py
Uses a throwaway database, so it never touches data/bumpin.db.
Stands in for the inbox pipeline by inserting the email rows directly.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.setdefault("BUMPIN_DB", os.path.join(tempfile.mkdtemp(), "demo.db"))

from backend.app import db  # noqa: E402
from backend.app.artists import RiderBlocked, routes, tickets  # noqa: E402,F401
from backend.app.artists import ripple  # noqa: E402

CLS = SimpleNamespace(confidence=0.95, entity_hint=None, is_major_change=False)
NOVA_EMAIL = {
    "from": "chris@novalane.example.test",
    "subject": "URGENT: flight cancelled",
    "body": "Hi Ravi, bad news: our flight from Sydney has been cancelled. We are rebooked and land at 9:40pm, "
            "so Nova Lane cannot make the 21:15 set. Chris",
    "attachments": [],
}


def receive(email: dict) -> int:
    """What the inbox pipeline will do: store the email and its attachments."""
    with db.get_conn() as conn:
        eid = conn.execute(
            "INSERT INTO emails (direction, from_addr, subject, body, received_at) VALUES ('in', ?, ?, ?, ?)",
            (email["from"], email["subject"], email["body"], "2026-11-30T10:00:00"),
        ).lastrowid
        for path in email["attachments"]:
            conn.execute(
                """INSERT INTO documents (owner_type, owner_id, kind, filename, path, received_at, email_id)
                   VALUES ('artist', 0, 'other', ?, ?, ?, ?)""",
                (Path(path).name, path, "2026-11-30T10:00:00", eid),
            )
    return eid


def show_ticket(tid: int) -> None:
    with db.get_conn() as conn:
        t = db.row(conn.execute("SELECT * FROM tickets WHERE id = ?", (tid,)))
        fs = db.rows(conn.execute("SELECT * FROM findings WHERE ticket_id = ?", (tid,)))
    print(f"  ticket {tid} [{t['type']}] status={t['status']} severity={t['severity']}")
    print(f"  summary: {t['summary']}")
    for f in fs:
        box = json.loads(f["bbox_json"] or "{}")
        where = f"page {box['page']} rect {box['rects'][0]}" if box.get("rects") else "no highlight"
        print(f"  - finding {f['id']} {f['kind']} ({f['severity']}): {f['message']}")
        print(f"    suggestion: {f['suggestion']}")
        print(f"    quote: \"{f['quote']}\", {where}")


def show_outbox(since: int = 0) -> int:
    with db.get_conn() as conn:
        rows = db.rows(conn.execute("SELECT * FROM outbox WHERE id > ? ORDER BY id", (since,)))
    for o in rows:
        print(f"  DRAFT to {o['to_addr']}: {o['subject']} (status {o['status']})")
        print("    " + o["body"].replace("\n", "\n    "))
    return rows[-1]["id"] if rows else since


def header(text: str) -> None:
    print("\n" + "=" * 70 + f"\n{text}\n" + "=" * 70)


def main() -> None:
    counts = db.reset()
    header(f"Reset: {counts}")

    emails = {p.name: json.loads(p.read_text()) for p in sorted((ROOT / "data/demo/emails").glob("*.json"))}

    header("Problem 1: Sparkle rider needs 3 CDJs, River Stage has 2")
    sparkle = tickets.create_rider_ticket(receive(emails["01_sparkle_rider.json"]), CLS)
    show_ticket(sparkle)
    try:
        tickets.RiderHandler().approve(sparkle, "ravi", None)
    except RiderBlocked as e:
        print(f"  approve without override is blocked: {e}")
    finding = tickets.open_conflicts(sparkle)[0]
    tickets.RiderHandler().resolve_finding(sparkle, finding["id"], "jess")
    print("  Jess clicked Resolve, reply drafted:")
    last = show_outbox()
    allocs = tickets.approve_rider(sparkle, "jess")
    print(f"  approved, allocations: {allocs}")

    header("Problem 2: Neon Tide (pasted rider) and Halcyon both need the one Moog")
    show_ticket(tickets.create_rider_ticket(receive(emails["02_neon_tide_rider_pasted.json"]), CLS))

    header("Problem 3: Marlow & The Lanes hospitality over the cap")
    show_ticket(tickets.create_rider_ticket(receive(emails["03_marlow_lanes_rider.json"]), CLS))

    header("Problem 6: Nova Lane flight cancelled, 4pm Saturday")
    nova = ripple.create_help_ticket(
        receive(NOVA_EMAIL), SimpleNamespace(confidence=0.95, entity_hint="Nova Lane", is_major_change=True))
    show_ticket(nova)
    with db.get_conn() as conn:
        actions = json.loads(conn.execute("SELECT proposed_actions_json FROM tickets WHERE id = ?",
                                          (nova,)).fetchone()[0])
    for a in actions:
        print(f"  action {a['index']}: {a['title']} | {a['detail']}")
    print("  Ravi approves every action from his phone:")
    for a in actions:
        ripple.HelpHandler().approve_action(nova, a["index"], "ravi")
    show_outbox(last)

    header("Overview")
    print(json.dumps(routes.overview(), indent=2))
    print(f"\nDatabase used: {db.DB_PATH}")


if __name__ == "__main__":
    main()
