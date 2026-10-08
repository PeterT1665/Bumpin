"""Fill the vendor board out for screenshots. `screenshot` branch only.

Three vendors and four columns left most of that board white. This adds three
more traders and the liquor documents the fifth column needs, and spreads the
document states so every column carries a mix rather than a stack of one
colour: a current certificate, one expiring inside the festival, one unreadable
and one simply not on file.

What it does NOT do is invent a file on disk. Every row here points at the
`path` of a document that already exists, because the vendor detail screen
renders that file and a dangling path is a broken pane rather than a card. The
board reads the row; the pane reads the file; only the row is new.

Idempotent.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "bumpin.db"

#: name, type, contact, email, gas, zone, load-in day/hours, status
NEW_VENDORS = [
    ("Pepper & Pine",  "food",     "Ines Vargas", "ines@pepperandpine.example.test",
     1, "River Food Court", "2026-12-11T07:30:00", "2026-12-11T09:30:00", "in_progress"),
    ("Low Tide Bar",   "beverage", "Rhys Okonkwo", "rhys@lowtidebar.example.test",
     0, "Pier Bar", "2026-12-11T06:00:00", "2026-12-11T08:00:00", "in_progress"),
    ("Second Press",   "merch",    "Mei Lindqvist", "mei@secondpress.example.test",
     0, "Grove Market", "2026-12-11T08:30:00", "2026-12-11T10:00:00", "in_progress"),
]

#: vendor name -> [(kind, filename stem, expiry or None, issuer)]
#:
#: `None` for an expiry is the "expiry unreadable" card; a date inside the
#: festival is the conflict card; a vendor with no row for a kind at all is the
#: "not on file" card, which is why some lists are deliberately short.
ISSUERS = {
    "food_safety": "Riverside City Council Environmental Health",
    "insurance": "Southern Cross Underwriters",
    "permit": "Riverside City Council",
    "gas": "Harbourside Gas Compliance Services",
    "liquor": "State Liquor Authority",
}

#: The gas column is labelled "Gas & electrical", so a stall with no burner
#: still has an electrical compliance certificate to file — which is also what
#: keeps that column from being two cards tall next to columns of five.
NEW_DOCS = {
    "Marlow Catering":   [("liquor", "2027-03-31"), ("gas", "2027-08-09")],
    "Smoke and Co":      [("gas", "2026-12-09"), ("liquor", None)],
    "Harbour Coffee Co": [("food_safety", "2027-07-14"), ("liquor", "2027-02-28"),
                          ("gas", None)],
    "Pepper & Pine":     [("food_safety", "2027-04-02"), ("insurance", "2027-09-30"),
                          ("permit", None), ("gas", "2027-06-18")],
    "Low Tide Bar":      [("insurance", "2027-11-05"), ("permit", "2027-01-31"),
                          ("liquor", "2026-12-08"), ("food_safety", "2027-02-20"),
                          ("gas", "2027-10-01")],
    "Second Press":      [("insurance", "2027-05-22"), ("permit", "2027-03-15"),
                          ("food_safety", None)],
}

RECEIVED = {
    "food_safety": "2026-11-21", "insurance": "2026-11-12", "permit": "2026-11-17",
    "gas": "2026-11-26", "liquor": "2026-11-23",
}


def main() -> None:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    if conn.execute("SELECT 1 FROM documents WHERE kind = 'liquor'").fetchone():
        print("Already built. Nothing to do.")
        return

    for row in NEW_VENDORS:
        if conn.execute("SELECT 1 FROM vendors WHERE name = ?", (row[0],)).fetchone():
            continue
        conn.execute(
            """INSERT INTO vendors (name, type, contact_name, contact_email, uses_gas,
                                    site_zone, load_in_start, load_in_end, status)
               VALUES (?,?,?,?,?,?,?,?,?)""", row)

    vendor_id = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM vendors")}

    # Every new row points at a PDF that is already on disk, so the detail pane
    # has something to render. Which one hardly matters on a board screenshot;
    # a missing one would be a blank pane, which does matter.
    stand_in = conn.execute(
        "SELECT path FROM documents WHERE owner_type='vendor' ORDER BY id LIMIT 1").fetchone()["path"]

    added = 0
    for name, docs in NEW_DOCS.items():
        vid = vendor_id[name]
        for kind, expiry in docs:
            if conn.execute(
                "SELECT 1 FROM documents WHERE owner_type='vendor' AND owner_id=? AND kind=?",
                (vid, kind)
            ).fetchone():
                continue
            slug = name.lower().replace(" & ", "_and_").replace(" ", "_")
            conn.execute(
                """INSERT INTO documents (owner_type, owner_id, kind, filename, path,
                                          extracted_text, expiry_date, issuer, received_at)
                   VALUES ('vendor', ?, ?, ?, ?, ?, ?, ?, ?)""",
                (vid, kind, f"{slug}_{kind}.pdf", stand_in,
                 f"{kind.replace('_', ' ').title()} for {name}.",
                 expiry, ISSUERS[kind], RECEIVED[kind]))
            added += 1

    conn.commit()
    print(f"{added} documents added across {len(vendor_id)} vendors\n")
    print(f"{'column':<14}{'current':>8}{'expiring':>9}{'unreadable':>11}{'missing':>8}")
    vendors = list(vendor_id.values())
    for kind in ("food_safety", "insurance", "gas", "permit", "liquor"):
        rows = {r["owner_id"]: r["expiry_date"] for r in conn.execute(
            "SELECT owner_id, expiry_date FROM documents WHERE owner_type='vendor' AND kind=?",
            (kind,))}
        missing = sum(1 for v in vendors if v not in rows)
        unreadable = sum(1 for e in rows.values() if e is None)
        expiring = sum(1 for e in rows.values() if e is not None and e <= "2026-12-13")
        current = len(rows) - unreadable - expiring
        print(f"{kind:<14}{current:>8}{expiring:>9}{unreadable:>11}{missing:>8}")


if __name__ == "__main__":
    main()
