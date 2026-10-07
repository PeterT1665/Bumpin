"""The decisions that give the rider board its three tints and the Equipment screen its numbers.

WHY
The board colours a card by the ticket's conflict tally, not by its status:
nothing raised or everything dealt with is green, raised and untouched is yellow,
part way through is pink (`frontend/src/screens/riders/riders.ts`, `tintFor`). So
pink cannot exist in the data until some ticket carries two or more conflicts with
one of them resolved or ignored. Every rider now raises two or three (see
`generate_festival.py`), and this script deals with one of them on five tickets and
all of them on two.

The result, which is what the board is checked against:

  Dome   Quiet Satellite green (raises none)   Indigo Machines pink 1/3
         Neon Tide yellow 0/3                  Dj Nova yellow 0/2
  Lawn   Paper Pines green 2/2                 Marlow & The Lanes pink 1/2
         Velvet Signal pink 1/3                Static Parade yellow 0/3
         Halcyon yellow 0/2
  River  Wild Hearts green 2/2                 Coastal Rivers pink 1/3
         Midnight Garden pink 1/3              Sparkle yellow 0/2

All three tints in all three columns, and exactly one card with no track at all.

The same goes for `inventory_items` / `allocations`. Nothing reserves equipment
except `approve_rider` (`backend/app/artists/tickets.py`), so until a rider is
approved the Equipment screen reads Fully booked 0 while the tickets beside it
claim equipment conflicts. Approving the three riders that have nothing open writes
the reservations through the API, the same POST the Approve button sends. No allocation row is
hand-written.

WHAT IT DOES, in order

1. Resolves or ignores conflicts: one on each of five tickets, both on two more.
   `ignored` counts as dealt with in the tally: it is a decision about the
   conflict, and the bar is about open versus closed, not which way it closed.
   Findings are addressed by (owner, kind, quote) rather than by id, because
   `process_rider` deletes and rewrites every rider finding on each ingest and
   the ids move.

2. Approves the three riders with nothing open against them: Quiet Satellite, which
   raised no conflict, and Wild Hearts and Paper Pines, whose conflicts step 1 has
   just cleared. `approve_rider` refuses while a conflict is open and no override is
   given, so step 1 has to come first. Two of the three overlap (Wild Hearts on River
   and Quiet Satellite on the Dome both play Friday 14:30 to 15:30) and each asks for
   one of the two shared keyboard stands, so the pool ends the run held by two
   different artists at once. That is the Equipment screen's Flag column with
   something in it. Where a cleared shortage asked for more than the stage owns, the
   reservation is capped at what exists, which is `min(requested, free)` in
   `approve_rider` and not something this script arranges.

3. Squares `artists.status` with the Readiness card. `readiness_pct` is
   `artists_ready / artists_scheduled`, counted off `status = 'completed'`, while
   the five-way arc counts paperwork; the seed marked every scheduled artist
   `completed`, so the hero read 90% beside an arc that said almost nothing was
   cleared. Here `completed` means what the arc means by cleared: paperwork in,
   nothing open. Everyone else booked onto the run sheet is `in_progress`.
   TO PUT THE OLD NUMBER BACK, if the flattering hero is wanted over a consistent
   card, this one statement is the whole change:
       UPDATE artists SET status = 'completed' WHERE set_start IS NOT NULL;

4. Moves the decision clocks into the simulated week. `decisions.now()` stamps
   the real wall clock, which is months behind `sim_today`, so an approved ticket
   would read as decided before the mail that created it arrived.

RUN ORDER
    seed_demo -> trim_vendors -> generate_festival -> ingest_initial
    -> enrich_highlights -> stage_demo_state (THIS, last)

It must be LAST. `ingest_initial` re-runs `process_rider`, which releases
allocations, clears `decided_by` and rewrites findings, so anything decided before
it is undone; `enrich_highlights` then adds the warning findings, which this script
deliberately leaves open.

RE-RUNNING is safe. A finding already resolved or ignored is skipped, an already
approved ticket is skipped, and steps 3 and 4 are idempotent statements.
"""
from __future__ import annotations

import json
import pathlib
import sqlite3
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "bumpin.db"
BASE = "http://localhost:8000/api"
ACTOR = "ravi"

#: (owner, finding kind, exact quote, how, why) for every conflict that gets dealt
#: with. Two shapes live here and they do different jobs on the board:
#:
#:   SOME of a ticket's conflicts dealt with -> the card is pink, and its bar reads
#:   as progress. Five tickets, one conflict each, spread so that every stage column
#:   carries a pink card.
#:
#:   ALL of a ticket's conflicts dealt with -> the card is green with a full bar, and
#:   `approve_rider` will accept it without an override. Wild Hearts and Paper Pines
#:   are the two; both are approved in step 2, which is what writes `allocations`.
#:   Quiet Satellite is green a third way, by raising nothing at all.
#:
#: `ignored` counts as dealt with either way: it is a decision about the conflict,
#: and the bar is about open versus closed, not which way it closed.
#:
#: The quotes are the rider lines as the extractor reads them, so each one appears in
#: `scripts/make_rider_pdfs.py` or `scripts/generate_festival.py` verbatim. If a
#: quantity moves there and not here, the run says so rather than silently skipping.
DECIDE_FINDINGS = [
    # --- all conflicts cleared: green, full bar, then approved -------------------
    ("Wild Hearts", "shortage", "3x Pioneer CDJ-3000", "resolve",
     "third deck hired in for the afternoon, it is one changeover"),
    ("Wild Hearts", "shortage", "8x DI box", "resolve",
     "the guest band brings its own two, so the River Stage six cover it"),
    ("Paper Pines", "shortage", "5x Monitor wedges", "resolve",
     "fifth wedge walked over from the River Stage between sets"),
    ("Paper Pines", "shortage", "8x Shure SM58", "resolve",
     "two mics hired in with the Sunday changeover package"),
    # --- one of several cleared: pink, part-filled bar ---------------------------
    ("Midnight Garden", "shortage", "10x Shure SM58", "ignore",
     "two spare vocal mics, the band can share"),
    ("Velvet Signal", "shortage", "2x DI box", "resolve",
     "River Stage lends its DI boxes across for the afternoon"),
    ("Indigo Machines", "shortage", "3x Monitor wedges", "resolve",
     "third wedge hired in with the Dome's own PA"),
    ("Marlow & The Lanes", "shortage", "6x Monitor wedges", "resolve",
     "two extra wedges come over from the River Stage after its last set"),
    ("Coastal Rivers", "shortage", "3x Pioneer CDJ-3000", "resolve",
     "third deck is the spare that lives in the River Stage flight case"),
]

#: Riders with nothing open against them by the time step 2 runs, so they approve
#: without an override. Approving is what writes `allocations`.
APPROVE = ["Wild Hearts", "Quiet Satellite", "Paper Pines"]

#: Inside sim_today (2026-11-30), after the last mail on Sunday 29 November.
DECIDED_AT = "2026-11-30T09:20:00"


def post(path: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else b"{}"
    req = urllib.request.Request(
        BASE + path, data=data, method="POST",
        headers={"Content-Type": "application/json", "X-User": ACTOR})
    try:
        return 200, json.load(urllib.request.urlopen(req, timeout=300))
    except urllib.error.HTTPError as e:
        return e.code, {"detail": e.read().decode()[:300]}


def rider_findings(conn) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT f.id, f.ticket_id, f.kind, f.quote, f.status, a.name AS owner
           FROM findings f
           JOIN tickets t ON t.id = f.ticket_id
           JOIN artists a ON t.owner_type = 'artist' AND a.id = t.owner_id
           WHERE t.type = 'rider_needs' ORDER BY f.id""").fetchall()


def main() -> None:
    try:
        urllib.request.urlopen(BASE + "/health", timeout=10)
    except Exception as e:                                   # noqa: BLE001
        raise SystemExit(f"backend is not answering on {BASE}: {e}")

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    # ---- 1. one conflict dealt with on each two-conflict ticket ----
    print("dealing with one conflict per two-conflict ticket")
    found = rider_findings(conn)
    for owner, kind, quote, how, why in DECIDE_FINDINGS:
        hits = [f for f in found if f["owner"] == owner and f["kind"] == kind and f["quote"] == quote]
        if not hits:
            print(f"  !! {owner:<18} no {kind} finding quoting {quote!r} — the rider or the manifest moved")
            continue
        f = hits[0]
        if f["status"] != "open":
            print(f"  {owner:<18} finding {f['id']} already {f['status']}, skipped")
            continue
        code, _ = post(f"/tickets/{f['ticket_id']}/findings/{f['id']}/{how}")
        print(f"  {owner:<18} t{f['ticket_id']:<3} {how:<8} finding {f['id']:<4} {quote:<20} "
              f"{'OK' if code == 200 else code}  ({why})")

    # ---- 2. approve the riders that fit ----
    print("\napproving the riders that fit the manifest")
    for name in APPROVE:
        t = conn.execute(
            """SELECT t.id, t.status FROM tickets t JOIN artists a ON a.id = t.owner_id
               WHERE t.type = 'rider_needs' AND t.owner_type = 'artist' AND a.name = ?""",
            (name,)).fetchone()
        if t is None:
            print(f"  !! {name:<18} has no rider ticket")
            continue
        if t["status"] == "approved":
            print(f"  {name:<18} t{t['id']:<3} already approved, skipped")
            continue
        code, out = post(f"/tickets/{t['id']}/approve")
        if code != 200:
            print(f"  !! {name:<18} t{t['id']:<3} refused {code}: {out.get('detail')}")
            continue
        held = conn.execute(
            """SELECT i.canonical_name, al.quantity FROM allocations al
               JOIN inventory_items i ON i.id = al.inventory_item_id
               JOIN artists a ON a.id = al.artist_id
               WHERE a.name = ? AND al.status = 'reserved' ORDER BY i.id""", (name,)).fetchall()
        print(f"  {name:<18} t{t['id']:<3} approved -> " +
              ", ".join(f"{h['quantity']}x {h['canonical_name']}" for h in held))

    # ---- 2a. one draft per reply, not one per run ----
    # `resolve_finding` drafts a reply every time it runs, and a re-ingest reopens
    # the finding it drafted for, so a second pass through this script leaves two
    # identical drafts in the outbox. `ticket_detail` only reads the newest, but
    # the Outbox screen lists them all. Keep the newest of each identical draft.
    dupes = conn.execute(
        """DELETE FROM outbox WHERE status = 'draft' AND id NOT IN (
               SELECT MAX(id) FROM outbox WHERE status = 'draft'
               GROUP BY ticket_id, to_addr, subject)""").rowcount
    if dupes:
        print(f"\ndropped {dupes} duplicate outbox draft(s) left by an earlier run")

    # ---- 3. status means the same thing as the arc ----
    cleared = """EXISTS (SELECT 1 FROM documents d WHERE d.owner_type = 'artist' AND d.owner_id = artists.id)
                 AND NOT EXISTS (SELECT 1 FROM tickets t JOIN findings f ON f.ticket_id = t.id
                                 WHERE t.owner_type = 'artist' AND t.owner_id = artists.id
                                   AND f.status = 'open')"""
    conn.execute(f"UPDATE artists SET status = 'completed' WHERE set_start IS NOT NULL AND ({cleared})")
    conn.execute(f"UPDATE artists SET status = 'in_progress' WHERE set_start IS NOT NULL AND NOT ({cleared})")
    conn.execute("UPDATE artists SET status = 'applied' WHERE set_start IS NULL")
    by_status = {r[0]: r[1] for r in conn.execute("SELECT status, COUNT(*) FROM artists GROUP BY status")}
    print(f"\nartist status squared with the readiness arc: {by_status}")

    # ---- 4. decision clocks inside the simulated week ----
    conn.execute("UPDATE tickets SET decided_at = ? WHERE decided_at IS NOT NULL AND decided_at < created_at",
                 (DECIDED_AT,))
    conn.execute("UPDATE tickets SET updated_at = MAX(created_at, COALESCE(decided_at, created_at))")
    conn.commit()
    span = conn.execute("SELECT MIN(created_at), MAX(updated_at) FROM tickets").fetchone()
    print(f"ticket clocks now span {span[0]} to {span[1]} (sim_today is "
          f"{conn.execute('SELECT sim_today FROM festival').fetchone()[0]})")
    conn.close()


if __name__ == "__main__":
    main()
