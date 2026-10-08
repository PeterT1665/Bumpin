"""Ingest the files Ravi uploads at the top of the demo.

The demo opens with an empty Bumpin: no inventory, and no conflicts that depend
on inventory. Ravi drops in the venue's own paperwork — the festival brief, the
policies and the equipment manifest — and the dashboard fills in. This script is
that upload.

Only the equipment manifest changes the database. The brief and the policies are
already the backend's own rules files (`data/rules/*.yaml`, `data/seed/festival.json`)
and are shipped as CSVs so they can be shown being uploaded; re-parsing them would
only write back what is already there, so the script reads them to report what
they contain and leaves them alone.

The manifest is parsed into `inventory_items`, and then the REAL rider pipeline
is re-run for every artist who has a rider on file: `process_rider` extracts the
rider again, re-matches each line against the newly loaded equipment, runs the
shortage / double-booking / hospitality checks, and rewrites the ticket's
findings. Nothing about the conflicts is hand-written — they fall out of the
manifest meeting the riders, which is the whole claim the demo makes.

Run after `clear_inventory.py` for the before/after, then `enrich_highlights.py`
to put the yellow caution highlights back (this rewrites rider findings).
"""
import csv
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.app import db                                    # noqa: E402
from backend.app.artists.tickets import process_rider         # noqa: E402

INITIAL = ROOT / "data" / "demo" / "initial"


def read_csv(name):
    with open(INITIAL / name, newline="") as f:
        return list(csv.DictReader(f))


def load_manifest(conn):
    """The equipment manifest becomes `inventory_items`. Stage names resolve to
    stage ids; anything not naming a known stage is the shared pool, which is
    what `stage_id IS NULL` means to the checks."""
    stages = {r["name"]: r["id"] for r in db.rows(conn.execute("SELECT id, name FROM stages"))}
    rows = read_csv("riverside_equipment_manifest.csv")
    # Both reference inventory_items, so they go first or the delete trips the
    # foreign key. Rider lines keep their row and lose only the stale match —
    # `process_rider` re-matches them against the manifest a moment later.
    conn.execute("DELETE FROM allocations")
    conn.execute("UPDATE rider_items SET inventory_item_id = NULL")
    conn.execute("DELETE FROM inventory_items")
    unknown = []
    for r in rows:
        stage = r["Stage"].strip()
        stage_id = stages.get(stage)
        if stage_id is None and stage.lower() not in ("shared pool", "", "shared"):
            unknown.append(stage)
        aliases = [a.strip() for a in r["Also known as"].split(";") if a.strip()]
        conn.execute(
            """INSERT INTO inventory_items (stage_id, canonical_name, category, quantity_total, aliases_json)
               VALUES (?, ?, ?, ?, ?)""",
            (stage_id, r["Item"].strip(), r["Category"].strip(),
             int(r["Quantity"]), json.dumps(aliases)),
        )
    return len(rows), sorted(set(unknown))


def latest_rider_docs(conn, artist_id):
    """The rider documents that the artist's MOST RECENT rider email brought in.

    Not every rider on file. An artist who sent a revised rider has both, and
    extracting both SUMS their lines: Sparkle's "3x CDJ-3000" becomes 6x and the
    finding lands on the superseded document instead of the one the ticket shows.
    Arrival order is id order, so the last one is the live one.

    But one email can carry more than one document, and two of them do. Sparkle's
    photo arrives with a typed addendum for the staging page the photo misses, and
    Dj Nova's handwritten page arrives with her manager's typed technical addendum.
    Those are one rider in two files, not a rider and its replacement, so both are
    extracted and the ticket's conflicts are counted across both. That is exactly
    what `create_rider_ticket` does with them on the way in, so this agrees with the
    live pipeline rather than contradicting it a step later.

    The grouping key is the EMAIL, which is why nothing else moves: every other rider
    arrived alone on its own email, so this returns the same single document the
    latest-rider-only rule returned. A rider seeded straight into the database with no
    email at all (Halcyon's, document 102) has `email_id IS NULL`, so it is returned on
    its own rather than grouped with every other NULL.
    """
    newest = db.row(conn.execute(
        """SELECT id, email_id FROM documents
           WHERE owner_type = 'artist' AND owner_id = ? AND kind = 'rider'
           ORDER BY id DESC LIMIT 1""", (artist_id,)))
    if newest["email_id"] is None:
        return [newest["id"]]
    return [r["id"] for r in db.rows(conn.execute(
        """SELECT id FROM documents
           WHERE owner_type = 'artist' AND owner_id = ? AND kind = 'rider' AND email_id = ?
           ORDER BY id""", (artist_id, newest["email_id"])))]


def main():
    with db.get_conn() as conn:
        before = conn.execute("SELECT COUNT(*) FROM inventory_items").fetchone()[0]
        n, unknown = load_manifest(conn)
        conn.commit()
    print(f"equipment manifest : {before} -> {n} inventory items")
    if unknown:
        print(f"  !! stage names nothing matched: {unknown} (filed as shared pool)")

    brief = read_csv("riverside_festival_brief.csv")
    pol = read_csv("riverside_hospitality_policy.csv")
    req = read_csv("riverside_vendor_requirements.csv")
    print(f"festival brief     : {len(brief)} fields  "
          f"({next((r['Value'] for r in brief if r['Field'] == 'Festival'), '?')})")
    print(f"hospitality policy : {len(pol) - 1} priced items, "
          f"cap {next((r['Unit cost AUD'] for r in pol if 'CAP' in r['Item']), '?')}")
    print(f"vendor rules       : {len(req)} vendor types")

    # Re-run the real pipeline for every artist who has a rider on file.
    with db.get_conn() as conn:
        artists = db.rows(conn.execute(
            """SELECT DISTINCT a.id, a.name FROM artists a
               JOIN documents d ON d.owner_type = 'artist' AND d.owner_id = a.id AND d.kind = 'rider'
               ORDER BY a.id"""))
        docs = {a["id"]: latest_rider_docs(conn, a["id"]) for a in artists}

    # Twice, deliberately. `process_rider` matches one artist's lines and then
    # immediately checks them, but the double-booking check looks at what OTHER
    # artists have matched — and on the first pass those artists have not been
    # re-matched yet, so a shared-pool clash is only visible from whichever side
    # happens to be processed last. The second pass runs with every rider
    # matched, so both sides of a clash see it. Rewriting findings is idempotent.
    print(f"\nre-running the rider checks against the new equipment ({len(artists)} artists)")
    for pass_no in (1, 2):
        for a in artists:
            tid = process_rider(a["id"], docs[a["id"]])
            if pass_no == 2:
                with db.get_conn() as conn:
                    found = db.rows(conn.execute(
                        "SELECT kind, severity FROM findings WHERE ticket_id = ? ORDER BY id", (tid,)))
                shape = ", ".join(f"{f['kind']}/{f['severity']}" for f in found) or "nothing flagged"
                docs_used = "+".join(str(d) for d in docs[a["id"]])
                print(f"  {a['name'][:22]:<23} ticket {tid:<4} doc {docs_used:<9} {shape}")


main()
