"""Give every vendor a ticket with conflicts on it. `screenshot` branch only.

A vendor card draws its bar from the vendor's latest ticket, so the three
traders added for this branch had no bar at all and the two that did had one
segment each. The board read as a wall of blank cards.

Note that one ticket feeds every card for that vendor, because the bar is per
VENDOR and the columns are per DOCUMENT. So a vendor with four conflicts shows
the same four-segment bar in all five columns. That is how the component
already worked; it is only visible now because there is something to show.

The colour is NOT affected: a vendor card is tinted by the state of the
document in that column (`toneForDocument`), not by this tally, so the spread
of pink, yellow and blue that screenshot_vendors.py set up survives.

Idempotent.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "bumpin.db"

MARKER = "screenshot-branch"

#: vendor -> (how many of its conflicts are already cleared, [(kind, message)])
#:
#: Cleared counts are spread so the bars are not all empty: a board where every
#: bar is untouched says nobody has done any work, which is the wrong thing for
#: a screenshot of a tool that does the work.
WORK = {
    "Marlow Catering": (1, [
        ("missing_doc", "No liquor licence on file, and the menu lists wine by the glass."),
        ("expired_cert", "Public liability names the trading name, not the registered entity."),
        ("missing_doc", "Staff food handling certificates have not been supplied."),
    ]),
    "Smoke and Co": (0, [
        ("expired_cert", "Gas compliance expires on 9 December, before the festival ends."),
        ("missing_doc", "No liquor licence on file against a stated expiry."),
        ("missing_doc", "Electrical test tags for the smoker are not on file."),
        ("expired_cert", "Council permit covers one pitch; two are booked."),
    ]),
    "Harbour Coffee Co": (3, [
        ("schedule_change", "Load-in moves from 07:00 to 05:30, before the gate is staffed."),
        ("missing_doc", "No waste management plan for the Lawn gate pitch."),
        ("expired_cert", "Insurance certificate predates the change of trading name."),
    ]),
    "Pepper & Pine": (1, [
        ("missing_doc", "Council permit is on file but carries no readable expiry."),
        ("expired_cert", "Gas certificate covers two burners; four are on the equipment list."),
        ("missing_doc", "No proof of public liability for the shared River pitch."),
        ("missing_doc", "Allergen statement has not been supplied for a food stall."),
    ]),
    "Low Tide Bar": (2, [
        ("expired_cert", "Liquor licence expires on 8 December, before the festival ends."),
        ("missing_doc", "No RSA certificates on file for the bar staff."),
        ("schedule_change", "Load-in at 06:00 is before the Pier access road opens."),
        ("expired_cert", "Food safety registration is for a fixed premises, not a stall."),
        ("missing_doc", "No waste or glass disposal plan for a bar pitch."),
    ]),
    "Second Press": (0, [
        ("missing_doc", "Food safety record is on file with no readable expiry."),
        ("missing_doc", "No fire certificate for the marquee over the Grove Market pitch."),
        ("expired_cert", "Public liability covers $5m; the site rules ask for $20m."),
    ]),
}

SUGGEST = {
    "missing_doc": "Ask the vendor for the document and hold the pitch until it lands.",
    "expired_cert": "Ask for a certificate that covers the festival, or stand the pitch down.",
    "schedule_change": "Approve the new window, or hold them to the one on file.",
}


def main() -> None:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    if conn.execute(
        "SELECT 1 FROM findings WHERE suggestion = ? AND kind IN ('missing_doc','expired_cert')",
        (MARKER,)
    ).fetchone():
        print("Already built. Nothing to do.")
        return

    for name, (cleared, rows) in WORK.items():
        v = conn.execute("SELECT id FROM vendors WHERE name = ?", (name,)).fetchone()
        assert v is not None, name
        vid = v["id"]

        # Reuse the vendor's existing ticket where there is one: a second ticket
        # for the same vendor would change which one `latest_ticket_id` points
        # at and orphan the findings already on the first.
        t = conn.execute(
            """SELECT id FROM tickets WHERE owner_type='vendor' AND owner_id=?
               ORDER BY id DESC LIMIT 1""", (vid,)).fetchone()
        if t is None:
            ticket_id = int(conn.execute(
                """INSERT INTO tickets (type, status, severity, summary, owner_type, owner_id,
                                        created_at, updated_at)
                   VALUES ('vendor_eligibility', 'needs_review', 'conflict', ?, 'vendor', ?,
                           '2026-11-26T09:00:00', '2026-11-30T09:00:00')""",
                (f"{name}: {rows[0][1]}", vid)).lastrowid)
        else:
            ticket_id = t["id"]

        for kind, message in rows:
            conn.execute(
                """INSERT INTO findings (ticket_id, kind, severity, message, suggestion,
                                         doc_id, quote, page, bbox_json, status)
                   VALUES (?, ?, 'conflict', ?, ?, NULL, NULL, NULL, NULL, 'open')""",
                (ticket_id, kind, message, MARKER))

        # Applied over the finished set, so "clear two" means two of the final
        # count rather than two of whatever was there before this run.
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM findings WHERE ticket_id=? AND severity='conflict' ORDER BY id",
            (ticket_id,))]
        for i, fid in enumerate(ids):
            conn.execute("UPDATE findings SET status=? WHERE id=?",
                         ("resolved" if i < cleared else "open", fid))

    conn.commit()

    print(f"{'vendor':<20}{'raised':>7}{'cleared':>9}")
    for r in conn.execute(
        """SELECT v.name, SUM(f.severity='conflict') raised,
                  SUM(f.severity='conflict' AND f.status!='open') cleared
           FROM vendors v
           LEFT JOIN tickets t ON t.owner_type='vendor' AND t.owner_id=v.id
           LEFT JOIN findings f ON f.ticket_id=t.id
           GROUP BY v.id ORDER BY v.id"""):
        print(f"{r['name']:<20}{r['raised'] or 0:>7}{r['cleared'] or 0:>9}")


if __name__ == "__main__":
    main()
