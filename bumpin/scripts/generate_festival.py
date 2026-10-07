"""Fill the festival behind the demo: a believable roster, eight more riders, mail spread over a week.

WHY
The product worked but the data behind it did not. Four of sixty artists had ever
sent a rider, so the dashboard read "0 cleared, 40 not started", the rider board
drew four cards in one tint, the intake chart had six empty weekday tracks and the
Equipment screen reported Items 16 / Fully booked 0 against tickets that claimed
equipment conflicts. None of that is a code bug; all of it is the dataset.

WHAT IT DOES, in order

0. Writes the Dj Nova artist row (id 61) if it is not already there. She is the
   demo's hero and is on the Dome Stage, which the rider board sorts leftmost.

1. Trims the artist roster from 60 (45 scheduled, 15 applied) to 28 (25 scheduled,
   3 applied). Three vendors are fixed, so the ratio lands at 8 artists per vendor:
   that is the smallest roster that still fills three day tabs with eight sets each
   and still leaves a "not started" bucket that does not dwarf the rest. It refuses
   to delete any artist that owns a document, a rider line, an allocation or a
   ticket, so every artist the demo names survives by construction.

2. Writes five new rider PDFs with `make_rider_pdfs.build`, which is reused rather
   than reimplemented so the text layer, fonts and page geometry stay identical to
   the three riders already on disk (`enrich_highlights` derives rects from that
   geometry and will abort if it ever changes). It also calls
   `scripts/make_djnova_rider.py`, which renders the handwritten page to an image,
   writes the OCR cache that page is read through, and builds its typed addendum.

3. Feeds nine new riders through the REAL inbox: `POST /api/inbox/receive`, same
   path the nine demo emails take. Five arrive as PDF attachments, three as text
   pasted into the email body, and Dj Nova's arrives as two attachments on one
   email, so all three document formats are represented among tickets that still
   have open findings. Nothing about the conflicts is written here. Every quantity
   is chosen against `data/demo/initial/riverside_equipment_manifest.csv` so that
   the shortage, double-booking and hospitality checks produce the intended finding
   when the pipeline runs:

     shortage        asks for more than the stage owns (Midnight Garden 4x CDJ-3000
                     on a 2-deck stage), or for something the stage does not own at
                     all (Velvet Signal's DI boxes, which only River Stage has)
     double_booking  two overlapping sets want the one shared Haze machine pool
                     (Indigo Machines and Static Parade, both 22:00 to 23:00)
     low_confidence  a line nothing in the manifest matches (Dj Nova's Pioneer
                     DJM-A9, a mixer the venue does not own). A warning, not a
                     conflict, and the only one in the set
     clean           one rider, Quiet Satellite, that fits the manifest exactly

   Every rider raises two or three conflicts except Quiet Satellite, which raises
   none. A ticket's bar is one segment per conflict, so a single-segment bar can
   never read as progress; two or three can, and `stage_demo_state` deals with one
   of them on five tickets and both of them on two.

4. Backdates `emails.received_at` across Mon 23 to Sun 29 November 2026, the week
   before `sim_today`, plus Dj Nova's on sim_today itself (a Monday), and moves each ticket's `created_at` and each document's
   `received_at` with it. The intake chart buckets mail by weekday; every email
   shared one timestamp, so six of its seven tracks were empty.

RUN ORDER
    POST /api/demo/reset
    scripts/seed_demo.py          nine demo emails
    scripts/trim_vendors.py       40 vendors -> 3
    scripts/generate_festival.py  THIS: roster, eight riders, mail spread
    scripts/ingest_initial.py     manifest -> inventory, then re-runs every rider
    scripts/enrich_highlights.py  the yellow caution boxes (must follow the above)
    scripts/stage_demo_state.py   the resolve / ignore / approve decisions

It must come BEFORE `ingest_initial`, because that is what re-runs `process_rider`
for every rider on file in two passes and so is the only thing that can see both
sides of a shared-pool clash. It must come before `enrich_highlights` for the same
reason `ingest_initial` does: `process_rider` deletes and rewrites rider findings.

RE-RUNNING is safe. The roster trim is a no-op once trimmed. An artist who already
has a rider document is skipped rather than sent a second rider (two riders on file
would make `ingest_initial` treat the first as superseded). The backdating is a
fixed subject-to-timestamp table, so it converges to the same clock every time.
"""
from __future__ import annotations

import json
import pathlib
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.make_djnova_rider import main as build_dj_nova  # noqa: E402
from scripts.make_rider_pdfs import build  # noqa: E402  same text layer as the seeded riders

DB = ROOT / "data" / "bumpin.db"
BASE = "http://localhost:8000/api"
RIDER_DIR = ROOT / "data" / "docs" / "riders"


# --------------------------------------------------------------------------- roster

#: Scheduled artists kept, grouped by festival day. Every artist that owns a
#: document, a ticket or a rider line is in here by necessity (the trim asserts
#: it); the rest are chosen to leave eight sets on each day tab, spread over the
#: three stages. Dusk Theory (6) has no paperwork but is the other half of ticket
#: 7's ripple, so it is named explicitly.
KEEP_SCHEDULED = [
    # Friday 11 December
    29,  # Northern Season    River 12:00
    18,  # Velvet Signal      Lawn  13:15   rider, 2 conflicts
    13,  # Wild Hearts        River 14:30   rider, clean
    42,  # Quiet Satellite    Dome  14:30   rider, clean
    28,  # Midnight Machines  Lawn  14:30
    12,  # Midnight Garden    River 18:15   rider, 2 conflicts
    1,   # Sparkle            River 20:00   ticket 2, showcase
    16,  # Static Arcade      Dome  20:45
    # Saturday 12 December
    15,  # Hollow Parade      River 12:00
    2,   # Halcyon            Lawn  18:00   ticket 1 + ticket 8
    21,  # Coastal Rivers     River 18:15   rider, 1 conflict
    3,   # Neon Tide          Dome  18:45   ticket 3, showcase
    30,  # Indigo Machines    Dome  22:00   rider, 2 conflicts
    38,  # Static Parade      Lawn  22:00   rider, 1 conflict
    5,   # Nova Lane          River 22:45   ticket 7, showcase
    6,   # Dusk Theory        River 23:00   the other half of ticket 7's ripple
    # Sunday 13 December
    26,  # Coastal Parade     Dome  12:00
    7,   # Electric Arcade    Lawn  13:15
    35,  # Electric Harbour   River 14:30
    34,  # Paper Pines        Lawn  15:45   rider, clean
    27,  # Lunar Union        Dome  15:45
    17,  # Northern Motel     River 17:00
    4,   # Marlow & The Lanes Lawn  19:00   ticket 4, showcase
    22,  # Golden Ferns       River 20:45
]

#: The hero ticket. Dj Nova is not in `data/seed/artists.json` as shipped, so the row is
#: written here as well as added to the seed file; `POST /demo/reset` reloads the seed,
#: this covers a database that was never reset. Dome Stage because the rider board sorts
#: its columns alphabetically by stage name (`RiderNeeds.tsx`, `stages.sort(localeCompare)`),
#: which puts Dome leftmost, and 20:15 to 21:45 because that is the 90 minute gap the
#: handwritten page asks for between Neon Tide (18:45) and Indigo Machines (22:00).
DJ_NOVA = {
    "id": 61, "name": "Dj Nova", "manager_name": "Mira Okafor",
    "manager_email": "mira@djnova.example.test", "stage_id": 3,
    "set_start": "2026-12-12T20:15:00", "set_end": "2026-12-12T21:45:00",
    "status": "in_progress", "hospitality_cap": None,
}
KEEP_SCHEDULED.append(DJ_NOVA["id"])

#: Unscheduled applicants kept. `readiness.not_received` counts exactly these, so
#: the bucket is empty without them and the arc loses a colour.
KEEP_APPLIED = [46, 47, 48]


def ensure_dj_nova(conn) -> str:
    cols = ", ".join(DJ_NOVA)
    marks = ", ".join("?" * len(DJ_NOVA))
    before = conn.execute("SELECT 1 FROM artists WHERE id = ?", (DJ_NOVA["id"],)).fetchone()
    conn.execute(f"INSERT OR REPLACE INTO artists ({cols}) VALUES ({marks})", tuple(DJ_NOVA.values()))
    return "already on the roster" if before else "added to the roster"


def trim_roster(conn) -> tuple[int, int]:
    keep = set(KEEP_SCHEDULED) | set(KEEP_APPLIED)
    before = conn.execute("SELECT COUNT(*) FROM artists").fetchone()[0]
    doomed = [r[0] for r in conn.execute("SELECT id FROM artists ORDER BY id") if r[0] not in keep]
    if not doomed:
        return before, before

    # Nothing with history is ever deleted. A dangling owner_id 404s a detail
    # screen and a dangling artist_id trips a foreign key, so this refuses rather
    # than cascades: if an artist has acquired paperwork, the keep list is wrong.
    marks = ",".join("?" * len(doomed))
    for table, col in (("documents", "owner_id"), ("rider_items", "artist_id"),
                       ("allocations", "artist_id"), ("tickets", "owner_id")):
        where = f"{col} IN ({marks})"
        if table in ("documents", "tickets"):
            where += " AND owner_type = 'artist'"
        rows = [r[0] for r in conn.execute(f"SELECT DISTINCT {col} FROM {table} WHERE {where}", doomed)]
        if rows:
            raise SystemExit(f"refusing to delete artists with {table} rows: {sorted(rows)}")

    conn.execute(f"DELETE FROM artists WHERE id IN ({marks})", doomed)
    after = conn.execute("SELECT COUNT(*) FROM artists").fetchone()[0]
    return before, after


# --------------------------------------------------------------------------- riders

#: Quantities are read against the manifest, not guessed:
#:   River  CDJ-3000 2, DJM-900 1, wedge 6, SM58 8, DI box 6, drum riser 1
#:   Lawn   CDJ-3000 2, DJM-900 1, wedge 4, SM58 6, mic stand 2
#:   Dome   CDJ-2000NXS2 2, wedge 2, SM58 4, booth monitor 2, mic stand 4
#:   Shared Moog One 1, Keyboard stand 2, Haze machine 2,
#:          Guest pass 12, Backstage pass 8, Parking space 6
#: "intent" records the finding each rider is built to produce, so a future change
#: to the manifest can be checked against what the demo expects.
#:
#: Every rider here now raises TWO OR THREE conflicts rather than nought to two. The
#: board's bar is one segment per conflict, so a one-segment bar cannot read as
#: progress and a bar with no segments reads as nothing to do. Quiet Satellite is the
#: single exception and stays clean on purpose: it is the only card left that
#: exercises the no-conflicts-no-track rendering.
PDF_RIDERS = [
    {
        "artist": "Wild Hearts",
        "file": "wild_hearts_rider.pdf",
        "from": "sasha@wildhearts.example.test",
        "subject": "Wild Hearts rider, River Stage Friday",
        "body": "Hi Riverside team,\n\nWild Hearts' technical and hospitality rider is attached "
                "for the River Stage set on Friday afternoon.\n\nThanks,\nSasha Moore",
        "intent": "2 shortages (3x CDJ-3000 against 2, 8x DI box against 6), both dealt with "
                  "before approval so the bar reads full and the card is green",
        "pages": [[
            ("h1", "WILD HEARTS: Technical and Hospitality Rider"),
            ("p", "Riverside Festival 2026, River Stage, Friday 11 December, 14:30 to 15:30"),
            ("p", "Management: Sasha Moore, sasha@wildhearts.example.test"),
            ("h2", "Technical requirements"),
            ("item", "3x Pioneer CDJ-3000"),
            ("item", "1x Pioneer DJM-900NXS2"),
            ("item", "2x Monitor wedges"),
            ("item", "2x Shure SM58"),
            ("item", "8x DI box"),
            ("note", "Full DI package for the guest band, we can drop to six if that is all there is."),
            ("item", "1x Keyboard stand"),
            ("h2", "Hospitality"),
            ("item", "6x Bottled water"),
            ("item", "1x Fruit platter"),
        ]],
    },
    {
        "artist": "Paper Pines",
        "file": "paper_pines_rider.pdf",
        "from": "riley@paperpines.example.test",
        "subject": "Paper Pines rider for Sunday",
        "body": "Hello,\n\nAttached is the Paper Pines rider for the Lawn Stage on Sunday. "
                "Hospitality is on the same page.\n\nBest,\nRiley Park",
        "intent": "2 shortages (5x wedge against 4, 8x SM58 against 6), both dealt with before "
                  "approval so the bar reads full and the card is green",
        "pages": [[
            ("h1", "PAPER PINES: Rider"),
            ("p", "Riverside Festival 2026, Lawn Stage, Sunday 13 December, 15:45 to 16:45"),
            ("p", "Management: Riley Park, riley@paperpines.example.test"),
            ("h2", "Technical requirements"),
            ("item", "2x Pioneer CDJ-3000"),
            ("item", "1x Pioneer DJM-900NXS2"),
            ("item", "5x Monitor wedges"),
            ("item", "8x Shure SM58"),
            ("h2", "Hospitality"),
            ("item", "12x Bottled water"),
            ("item", "1x Fruit platter"),
            ("item", "4x Towels"),
        ]],
    },
    {
        "artist": "Velvet Signal",
        "file": "velvet_signal_rider.pdf",
        "from": "alex@velvetsignal.example.test",
        "subject": "Velvet Signal technical rider",
        "body": "Hi,\n\nVelvet Signal's rider is attached. The mixer count is deliberate, "
                "please come back to us if that is a problem.\n\nAlex Kim",
        "intent": "3 shortages: 3x CDJ-3000 against 2, 3x DJM-900NXS2 on a 1-mixer stage, and "
                  "DI boxes Lawn Stage does not own. The DI box one is resolved, so the card is pink",
        "pages": [[
            ("h1", "VELVET SIGNAL: Technical Rider"),
            ("p", "Riverside Festival 2026, Lawn Stage, Friday 11 December, 13:15 to 14:15"),
            ("p", "Management: Alex Kim, alex@velvetsignal.example.test"),
            ("h2", "Technical requirements"),
            ("item", "3x Pioneer CDJ-3000"),
            ("item", "3x Pioneer DJM-900NXS2"),
            ("note", "One mixer per deck pair plus a spare on the riser."),
            ("item", "2x Monitor wedges"),
            ("item", "2x DI box"),
            ("h2", "Hospitality"),
            ("item", "8x Bottled water"),
            ("item", "4x Towels"),
        ]],
    },
    {
        "artist": "Midnight Garden",
        "file": "midnight_garden_rider.pdf",
        "from": "drew@midnightgarden.example.test",
        "subject": "Midnight Garden rider, River Stage",
        "body": "Hi team,\n\nRider attached for Midnight Garden. Four decks for the b2b, "
                "and the vocal mic count is for the full band.\n\nDrew Patel",
        "intent": "3 shortages: 4x CDJ-3000 against 2, 10x SM58 against 8, 2x drum riser against 1. "
                  "The SM58 one is ignored, so the card is pink",
        "pages": [[
            ("h1", "MIDNIGHT GARDEN: Rider"),
            ("p", "Riverside Festival 2026, River Stage, Friday 11 December, 18:15 to 19:15"),
            ("p", "Management: Drew Patel, drew@midnightgarden.example.test"),
            ("h2", "Technical requirements"),
            ("item", "4x Pioneer CDJ-3000"),
            ("note", "Four decks, back to back changeover without a gap."),
            ("item", "10x Shure SM58"),
            ("item", "2x Monitor wedges"),
            ("item", "2x Drum riser"),
            ("h2", "Hospitality"),
            ("item", "6x Bottled water"),
            ("item", "1x Fruit platter"),
        ]],
    },
    {
        "artist": "Indigo Machines",
        "file": "indigo_machines_rider.pdf",
        "from": "quinn@indigomachines.example.test",
        "subject": "Indigo Machines rider for the Dome",
        "body": "Hi Riverside,\n\nIndigo Machines rider attached for the Dome Stage on Saturday "
                "night. Haze is a big part of the show.\n\nQuinn Hart",
        "intent": "2 shortages (3x CDJ-2000NXS2 against 2, 3x wedge against 2) plus the Haze machine "
                  "clash with Static Parade. The wedge one is resolved, so the card is pink",
        "pages": [[
            ("h1", "INDIGO MACHINES: Rider"),
            ("p", "Riverside Festival 2026, Dome Stage, Saturday 12 December, 22:00 to 23:00"),
            ("p", "Management: Quinn Hart, quinn@indigomachines.example.test"),
            ("h2", "Technical requirements"),
            ("item", "3x Pioneer CDJ-2000NXS2"),
            ("item", "3x Monitor wedges"),
            ("item", "2x Shure SM58"),
            ("item", "2x Haze machine"),
            ("h2", "Hospitality"),
            ("item", "6x Bottled water"),
            ("item", "1x Sushi platter"),
            ("item", "6x Dinner for crew"),
        ]],
    },
]

#: Riders pasted into the email body. `create_rider_ticket` stores the body as a
#: text document, so these are the tickets whose highlights use character offsets
#: rather than rectangles. "TECH" and "HOSPO" are what the extractor reads as
#: section headings.
TEXT_RIDERS = [
    {
        "artist": "Quiet Satellite",
        "from": "avery@quietsatellite.example.test",
        "subject": "Quiet Satellite rider (pasted below)",
        "intent": "clean, and the ONLY clean rider left. Dome Stage exactly, which is what books "
                  "it out once approved, and the one card that draws no conflict track at all",
        "body": "Hi Riverside,\n\nThe PDF is still with our designer so here is the rider inline.\n\n"
                "TECH\n2x Pioneer CDJ-2000NXS2\n2x Monitor wedges\n4x Shure SM58\n1x Keyboard stand\n\n"
                "HOSPO\n8x Bottled water\n1x Cheese platter\n\nThanks,\nAvery Cole\nQuiet Satellite",
    },
    {
        "artist": "Coastal Rivers",
        "from": "avery@coastalrivers.example.test",
        "subject": "Coastal Rivers rider (no PDF sorry)",
        "intent": "3 shortages: 3x CDJ-3000 against 2, 8x monitor wedges against 6, 10x SM58 "
                  "against 8. The deck one is resolved, so the card is pink",
        "body": "Hey team,\n\nNo PDF this time, pasting the rider straight in.\n\n"
                "TECH\n3x Pioneer CDJ-3000\n1x Pioneer DJM-900NXS2\n8x Monitor wedges\n10x Shure SM58\n\n"
                "HOSPO\n8x Bottled water\n1x Cheese platter\n8x Dinner for crew\n\nCheers,\nAvery Cole",
    },
    {
        "artist": "Static Parade",
        "from": "drew@staticparade.example.test",
        "subject": "Static Parade rider, hospo included",
        "intent": "the other half of the Haze machine clash with Indigo Machines, plus 5x wedge "
                  "against the Lawn's 4 and 8x SM58 against its 6. Nothing dealt with, so it is yellow",
        "body": "Hi all,\n\nRider below, hospitality at the bottom.\n\n"
                "TECH\n2x Pioneer CDJ-3000\n1x Pioneer DJM-900NXS2\n5x Monitor wedges\n8x Shure SM58\n"
                "2x Haze machine\n\nHOSPO\n8x Bottled water\n1x Cheese platter\n\n"
                "Thanks,\nDrew Patel\nStatic Parade",
    },
]

#: The hero. One email, TWO attachments: the photographed handwritten page and the
#: manager's typed addendum. Both are built by `scripts/make_djnova_rider.py`, which
#: also writes the OCR cache the handwriting is read through.
#:
#: Two attachments on one email is the point. `create_rider_ticket` files every
#: document on the email against the artist and passes all of them to `process_rider`,
#: so one ticket carries a handwritten image and a text-layer PDF, and the conflict bar
#: counts across both. The subject has to contain the word "rider": the keyword
#: classifier reads it at 0.95, and anything under 0.90 adds a low-confidence warning
#: that would spoil the exactly-one-warning count.
DJ_NOVA_EMAIL = {
    "artist": "Dj Nova",
    "from": DJ_NOVA["manager_email"],
    "subject": "Dj Nova rider, handwritten page plus technical addendum",
    "body": "Hi Riverside,\n\nNova writes her rider out by hand and I have never talked her out "
            "of it, so here is a photo of the page. I have typed up the stage plot separately "
            "because her handwriting is what it is.\n\nThanks,\nMira Okafor",
    "attachments": ["data/docs/riders/dj_nova_rider_handwritten.png",
                    "data/docs/riders/dj_nova_addendum.pdf"],
    "intent": "2 conflicts and exactly 1 warning. On the handwriting: 4x CDJ-3000 is a shortage "
              "(the Dome owns none) and the Pioneer DJM-A9 matches nothing in the manifest, which "
              "is the warning. On the addendum: 6x Shure SM58 against the Dome's 4. Every other "
              "line matches, including the booth monitor, the mic stand and the passes.",
}


# ------------------------------------------------------------------------ backdate

#: The week before sim_today (2026-11-30). Keyed by (from_addr, subject) so it
#: survives a reseed that renumbers emails. Mid-week is heaviest; no weekday is
#: empty, which is the whole point of the intake chart.
MAIL_CLOCK = {
    # Monday 23 November
    ("sasha@wildhearts.example.test", "Wild Hearts rider, River Stage Friday"): "2026-11-23T09:10:00",
    ("dana@harbourcoffee.example.test", "Harbour Coffee Co: load-in change"): "2026-11-23T15:45:00",
    # Tuesday 24 November
    ("avery@quietsatellite.example.test", "Quiet Satellite rider (pasted below)"): "2026-11-24T08:40:00",
    ("tom@marlowcatering.example.test",
     "Marlow Catering: food safety certificate for Riverside"): "2026-11-24T11:15:00",
    ("alex@velvetsignal.example.test", "Velvet Signal technical rider"): "2026-11-24T15:20:00",
    # Wednesday 25 November
    ("sam@sparkle-mgmt.example.test", "Sparkle rider for Riverside"): "2026-11-25T08:20:00",
    ("riley@paperpines.example.test", "Paper Pines rider for Sunday"): "2026-11-25T11:05:00",
    ("jo@smokeandco.example.test", "Smoke and Co: insurance certificate"): "2026-11-25T16:40:00",
    # Thursday 26 November
    ("drew@midnightgarden.example.test", "Midnight Garden rider, River Stage"): "2026-11-26T09:35:00",
    # The photo supersedes the Wednesday PDF, so it must arrive after it.
    ("sam@sparkle-mgmt.example.test", "Sparkle rider (photo of the printed copy)"): "2026-11-26T13:05:00",
    # Friday 27 November
    ("drew@staticparade.example.test", "Static Parade rider, hospo included"): "2026-11-27T10:15:00",
    ("ada@marlowlanes.example.test", "Marlow & The Lanes: updated rider"): "2026-11-27T14:30:00",
    # Saturday 28 November. Neon Tide's body quotes a chase sent on 24 November.
    ("leo@neontide.example.test", "Re: Re: Fwd: Neon Tide rider (finally!)"): "2026-11-28T09:45:00",
    # Sunday 29 November. Both of these used to land midweek and were moved here when
    # the two help-ticket emails were cut: Nova Lane's cancellation and Halcyon's
    # one-liner were the ONLY Sunday mail, and the intake chart draws seven weekday
    # tracks. Without a replacement its Sunday track reads zero, which says the
    # festival went quiet rather than that two emails were removed from a demo.
    ("avery@coastalrivers.example.test", "Coastal Rivers rider (no PDF sorry)"): "2026-11-29T11:20:00",
    ("quinn@indigomachines.example.test", "Indigo Machines rider for the Dome"): "2026-11-29T16:40:00",
    # Monday 30 November, sim_today itself, and the most recent mail in the building.
    # `GET /tickets` orders by `updated_at DESC, id DESC` and the board lays its cards
    # out in that order, so this timestamp is what puts Dj Nova at the top of the Dome
    # column. It has to beat `stage_demo_state.DECIDED_AT` (09:20 the same morning),
    # which is what the approved tickets' `updated_at` becomes.
    (DJ_NOVA["manager_email"],
     "Dj Nova rider, handwritten page plus technical addendum"): "2026-11-30T10:05:00",
}

#: Halcyon's rider (ticket 1, document 102) was seeded straight into the database
#: with no email, so it has no row in the table above and needs its own clock.
ORPHAN_CLOCK = {"ticket": {1: "2026-11-23T10:30:00"}, "document": {102: "2026-11-23T10:30:00"}}

WEEK = ("2026-11-23", "2026-11-29")


def backdate(conn) -> dict[str, int]:
    first, last = (date.fromisoformat(d) for d in WEEK)
    if first.weekday() != 0 or last.weekday() != 6:
        raise SystemExit(f"{WEEK} is not a Mon-to-Sun week; the intake chart would skew")

    touched = {"emails": 0, "documents": 0, "tickets": 0, "unmapped": 0}
    for e in conn.execute("SELECT id, from_addr, subject FROM emails WHERE direction = 'in'").fetchall():
        when = MAIL_CLOCK.get((e[1], e[2]))
        if when is None:
            touched["unmapped"] += 1
            print(f"  !! no clock for email {e[0]}: {e[1]} / {e[2]!r}")
            continue
        conn.execute("UPDATE emails SET received_at = ? WHERE id = ?", (when, e[0]))
        touched["emails"] += 1
        touched["documents"] += conn.execute(
            "UPDATE documents SET received_at = ? WHERE email_id = ?", (when, e[0])).rowcount

    # A ticket is as old as the first mail that landed on it, or the chart and the
    # table's Received column disagree with each other.
    touched["tickets"] = conn.execute(
        """UPDATE tickets SET created_at = (
               SELECT MIN(e.received_at) FROM emails e WHERE e.ticket_id = tickets.id)
           WHERE EXISTS (SELECT 1 FROM emails e WHERE e.ticket_id = tickets.id)""").rowcount
    for tid, when in ORPHAN_CLOCK["ticket"].items():
        touched["tickets"] += conn.execute(
            "UPDATE tickets SET created_at = ? WHERE id = ?", (when, tid)).rowcount
    for did, when in ORPHAN_CLOCK["document"].items():
        touched["documents"] += conn.execute(
            "UPDATE documents SET received_at = ? WHERE id = ?", (when, did)).rowcount
    conn.execute("UPDATE tickets SET updated_at = created_at WHERE updated_at < created_at")
    return touched


# ----------------------------------------------------------------------------- api

def post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "X-User": "ravi"})
    try:
        return json.load(urllib.request.urlopen(req, timeout=300))
    except urllib.error.HTTPError as e:
        return {"error": e.code, "body": e.read().decode()[:400]}


def has_rider(conn, name: str) -> bool:
    row = conn.execute(
        """SELECT 1 FROM documents d JOIN artists a ON a.id = d.owner_id
           WHERE d.owner_type = 'artist' AND d.kind = 'rider' AND a.name = ?""", (name,)).fetchone()
    return row is not None


# ---------------------------------------------------------------------------- main

def main() -> None:
    try:
        urllib.request.urlopen(BASE + "/health", timeout=10)
    except Exception as e:                                   # noqa: BLE001
        raise SystemExit(f"backend is not answering on {BASE}: {e}")

    conn = sqlite3.connect(DB)

    print(f"Dj Nova    {ensure_dj_nova(conn)}")
    conn.commit()

    before, after = trim_roster(conn)
    conn.commit()
    sched = conn.execute("SELECT COUNT(*) FROM artists WHERE set_start IS NOT NULL").fetchone()[0]
    print(f"roster     {before} -> {after} artists ({sched} scheduled, {after - sched} applied)")

    print()
    build_dj_nova()

    print("\nrider PDFs")
    for r in PDF_RIDERS:
        build(r["file"], r["pages"])
        print(f"  {r['file']:<32} {r['intent']}")

    print("\nfeeding riders through POST /inbox/receive")
    for r in PDF_RIDERS + TEXT_RIDERS + [DJ_NOVA_EMAIL]:
        if has_rider(conn, r["artist"]):
            print(f"  {r['artist']:<18} already has a rider on file, skipped")
            continue
        out = post("/inbox/receive", {
            "from": r["from"], "subject": r["subject"], "body": r["body"],
            "attachments": r.get("attachments",
                                 [f"data/docs/riders/{r['file']}"] if "file" in r else []),
        })
        if "error" in out:
            print(f"  {r['artist']:<18} ERROR {out['error']} {out['body'][:160]}")
            continue
        fmt = "both" if "attachments" in r else "pdf " if "file" in r else "text"
        print(f"  {r['artist']:<18} {fmt} ticket={out['ticket_id']:<4} "
              f"{out['classification']['label']:<7} conf={out['classification']['confidence']}")

    print("\nbackdating mail across the week before sim_today")
    counts = backdate(conn)
    conn.commit()
    print(f"  emails {counts['emails']}, documents {counts['documents']}, "
          f"tickets {counts['tickets']}, unmapped {counts['unmapped']}")
    by_weekday = {}
    for row in conn.execute(
        """SELECT substr(received_at, 1, 10) AS d, COUNT(*) FROM emails
           WHERE direction = 'in' GROUP BY d ORDER BY d"""):
        day = date.fromisoformat(row[0]).strftime("%a")
        by_weekday[day] = by_weekday.get(day, 0) + row[1]
        print(f"  {row[0]}  {day}  {'#' * row[1]} {row[1]}")
    # The chart has seven tracks whatever the data does, so an empty one is a hole in
    # the card rather than a fact about the week.
    empty = [d for d in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun") if not by_weekday.get(d)]
    print(f"  weekday totals {by_weekday}")
    if empty:
        print(f"  !! the intake chart would draw empty tracks for {empty}")
    conn.close()
    print("\nnow run: ingest_initial.py -> enrich_highlights.py -> stage_demo_state.py")


if __name__ == "__main__":
    main()
