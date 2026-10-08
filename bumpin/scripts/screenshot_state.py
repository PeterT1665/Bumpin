"""Fill both boards out for screenshots.

This script exists only on the `screenshot` branch. It is not part of the demo:
`demo-reset` on `frontend` restores a database this has never touched. What it
builds is a board worth photographing — five populated columns on each, cards
in all three tints, and most tickets carrying three to five conflicts so the
progress bars have something to show.

Everything it writes is plausible rather than merely present. A new act gets a
stage, a set time that does not collide with the acts already on that stage, a
manager with an address, and conflicts that name equipment the stage actually
owns. A screenshot of a board full of obvious filler is worth less than one of
a board that is simply busy.

Idempotent: run it twice and the second run changes nothing.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "bumpin.db"

# Two more stages, so the board has five columns of cards rather than three.
NEW_STAGES = ["Grove Stage", "Pier Stage"]

#: name, manager, email, stage, set start, hospitality cap
NEW_ARTISTS = [
    ("Ferrous Youth",  "Noa Adeyemi",  "noa@ferrousyouth.example.test",   "Grove Stage", "2026-12-11T18:30:00", 900),
    ("Saltwater Choir", "Imogen Blake", "imogen@saltwaterchoir.example.test", "Grove Stage", "2026-12-12T20:00:00", 1200),
    ("Tin Palace",     "Rafa Duarte",  "rafa@tinpalace.example.test",     "Grove Stage", "2026-12-13T19:15:00", 800),
    ("Long Division",  "Kit Moreau",   "kit@longdivision.example.test",   "Pier Stage",  "2026-12-11T19:45:00", 1000),
    ("Harrow Lane",    "Suki Tan",     "suki@harrowlane.example.test",    "Pier Stage",  "2026-12-12T21:30:00", 1500),
    ("Pale Fiction",   "Bo Ferreira",  "bo@palefiction.example.test",     "Pier Stage",  "2026-12-13T17:00:00", 700),
]

#: Conflicts per new ticket. The first entry decides the card's umbrella, since
#: the board heads a card with the worst open finding and these are all the same
#: severity — so varying the first kind varies the headings down a column.
#:
#: `cleared` is how many of them are already dealt with, which is the only thing
#: the tint reads: none cleared is yellow, all cleared is green, part way is
#: pink. The spread here is deliberate.
NEW_TICKETS = [
    ("Ferrous Youth", 4, 1, [
        ("shortage", "Rider asks for 4x Shure SM58, Grove Stage has 2."),
        ("shortage", "Rider asks for 2x Monitor wedge, Grove Stage has 1."),
        ("double_booking", "Grove Stage DI boxes are held by two acts at 18:30."),
        ("shortage", "Rider asks for 1x Drum riser, Grove Stage has none."),
    ]),
    ("Saltwater Choir", 5, 5, [
        ("over_budget", "Hospitality comes to $1,410 against a $1,200 cap."),
        ("shortage", "Rider asks for 6x Vocal mic, Grove Stage has 4."),
        ("shortage", "Rider asks for 3x Monitor wedge, Grove Stage has 1."),
        ("double_booking", "Grove Stage piano is held by two acts at 20:00."),
        ("shortage", "Rider asks for 2x Keyboard stand, Grove Stage has 1."),
    ]),
    ("Tin Palace", 3, 0, [
        ("double_booking", "Grove Stage backline is held by two acts at 19:15."),
        ("shortage", "Rider asks for 2x Guitar amp, Grove Stage has 1."),
        ("shortage", "Rider asks for 4x DI box, Grove Stage has 2."),
    ]),
    ("Long Division", 4, 2, [
        ("shortage", "Rider asks for 3x Pioneer CDJ-3000, Pier Stage has 2."),
        ("over_budget", "Hospitality comes to $1,180 against a $1,000 cap."),
        ("shortage", "Rider asks for 2x Booth monitor speaker, Pier Stage has 1."),
        ("shortage", "Rider asks for 6x Shure SM58, Pier Stage has 4."),
    ]),
    ("Harrow Lane", 5, 0, [
        ("over_budget", "Hospitality comes to $1,760 against a $1,500 cap."),
        ("shortage", "Rider asks for 4x Monitor wedge, Pier Stage has 2."),
        ("shortage", "Rider asks for 2x Drum riser, Pier Stage has 1."),
        ("double_booking", "Pier Stage mixer is held by two acts at 21:30."),
        ("shortage", "Rider asks for 8x DI box, Pier Stage has 4."),
    ]),
    ("Pale Fiction", 3, 3, [
        ("shortage", "Rider asks for 2x Guitar amp, Pier Stage has 1."),
        ("shortage", "Rider asks for 4x Shure SM58, Pier Stage has 2."),
        ("shortage", "Rider asks for 1x Keyboard stand, Pier Stage has none."),
    ]),
]

#: Conflicts added to tickets that already exist, to bring every card into the
#: three-to-five band. Keyed by artist name, and matched on the artist's id
#: rather than that name, because nothing in this schema makes names unique.
TOP_UP = {
    "Neon Tide": [("over_budget", "Hospitality comes to $1,240 against a $1,100 cap.")],
    "Dj Nova": [],                      # scripted elsewhere; left exactly as it is
    "Quiet Satellite": [],              # the one clean card on the board, on purpose
    "Halcyon": [
        ("shortage", "Rider asks for 2x Monitor wedge, Lawn Stage has 1."),
        ("double_booking", "Lawn Stage DI boxes are held by two acts at 21:00."),
    ],
    "Marlow & The Lanes": [
        ("shortage", "Rider asks for 3x Guitar amp, Lawn Stage has 2."),
        ("over_budget", "Hospitality comes to $980 against a $900 cap."),
    ],
    "Paper Pines": [
        ("shortage", "Rider asks for 2x Drum riser, Lawn Stage has 1."),
        ("shortage", "Rider asks for 4x DI box, Lawn Stage has 3."),
    ],
    "Velvet Signal": [("double_booking", "Lawn Stage mixer is held by two acts at 19:30.")],
    "Static Parade": [("shortage", "Rider asks for 2x Keyboard stand, Lawn Stage has 1.")],
    "Sparkle": [
        ("shortage", "Rider asks for 3x Monitor wedge, River Stage has 2."),
        ("over_budget", "Hospitality comes to $1,320 against a $1,200 cap."),
    ],
    "Wild Hearts": [("double_booking", "River Stage drum riser is held by two acts at 20:45.")],
    "Midnight Garden": [("shortage", "Rider asks for 2x Guitar amp, River Stage has 1.")],
    "Coastal Rivers": [("over_budget", "Hospitality comes to $1,090 against a $950 cap.")],
    "Indigo Machines": [("shortage", "Rider asks for 2x Booth monitor speaker, Dome Stage has 1.")],
}

#: How many of each existing ticket's conflicts end up cleared, so the board
#: carries all three tints instead of a wall of one. `None` leaves it alone.
TINTS = {
    "Halcyon": 0,              # yellow: raised, none cleared
    "Marlow & The Lanes": 4,   # green: everything cleared
    "Paper Pines": 2,          # pink: part way
    "Velvet Signal": 0,        # yellow
    "Static Parade": 4,        # green
    "Sparkle": 2,              # pink
    "Wild Hearts": 3,          # green
    "Midnight Garden": 1,      # pink
    "Coastal Rivers": 0,       # yellow
    "Neon Tide": 4,            # green
    "Indigo Machines": 2,      # pink
}

SUGGEST = {
    "shortage": "Ask the act to work with what the stage owns, or hire the difference in.",
    "double_booking": "Move one of the two sets, or find a second of the item for the overlap.",
    "over_budget": "Trim the rider back to the cap, or get the overspend signed off.",
}

MARKER = "screenshot-branch"


def main() -> None:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    if conn.execute("SELECT 1 FROM findings WHERE suggestion = ?", (MARKER,)).fetchone():
        print("Already built. Nothing to do.")
        return

    stage_id = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM stages")}
    for name in NEW_STAGES:
        if name not in stage_id:
            stage_id[name] = int(conn.execute(
                "INSERT INTO stages (name) VALUES (?)", (name,)).lastrowid)

    # --- the two new columns ------------------------------------------------
    for name, manager, email, stage, start, cap in NEW_ARTISTS:
        if conn.execute("SELECT 1 FROM artists WHERE name = ?", (name,)).fetchone():
            continue
        end = f"{start[:11]}{int(start[11:13]) + 1:02d}{start[13:]}"
        conn.execute(
            """INSERT INTO artists (name, manager_name, manager_email, stage_id,
                                    set_start, set_end, status, hospitality_cap)
               VALUES (?, ?, ?, ?, ?, ?, 'in_progress', ?)""",
            (name, manager, email, stage_id[stage], start, end, cap))

    artist_id = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM artists")}

    for who, raised, cleared, rows in NEW_TICKETS:
        aid = artist_id[who]
        if conn.execute(
            "SELECT 1 FROM tickets WHERE owner_type='artist' AND owner_id=? AND type='rider_needs'",
            (aid,)
        ).fetchone():
            continue
        assert len(rows) == raised, (who, len(rows), raised)
        ticket_id = int(conn.execute(
            """INSERT INTO tickets (type, status, severity, summary, owner_type, owner_id,
                                    created_at, updated_at)
               VALUES ('rider_needs', ?, 'conflict', ?, 'artist', ?,
                       '2026-11-28T10:00:00', '2026-11-30T10:00:00')""",
            ("resolved" if cleared >= raised else "needs_review",
             f"{who}: {rows[0][1]}", aid)).lastrowid)
        for i, (kind, message) in enumerate(rows):
            conn.execute(
                """INSERT INTO findings (ticket_id, kind, severity, message, suggestion,
                                         doc_id, quote, page, bbox_json, status)
                   VALUES (?, ?, 'conflict', ?, ?, NULL, NULL, NULL, NULL, ?)""",
                (ticket_id, kind, message, MARKER,
                 "resolved" if i < cleared else "open"))

    # --- bring the existing cards into the three-to-five band ---------------
    for who, extra in TOP_UP.items():
        aid = artist_id.get(who)
        if aid is None:
            continue
        row = conn.execute(
            "SELECT id FROM tickets WHERE owner_type='artist' AND owner_id=? AND type='rider_needs'",
            (aid,)).fetchone()
        if row is None:
            continue
        for kind, message in extra:
            conn.execute(
                """INSERT INTO findings (ticket_id, kind, severity, message, suggestion,
                                         doc_id, quote, page, bbox_json, status)
                   VALUES (?, ?, 'conflict', ?, ?, NULL, NULL, NULL, NULL, 'open')""",
                (row["id"], kind, message, MARKER))

    # --- spread the tints ----------------------------------------------------
    # Applied last, over the finished set of conflicts, so "clear three of them"
    # means three of the final count rather than three of whatever existed when
    # the script started.
    for who, cleared in TINTS.items():
        aid = artist_id.get(who)
        if aid is None:
            continue
        row = conn.execute(
            "SELECT id FROM tickets WHERE owner_type='artist' AND owner_id=? AND type='rider_needs'",
            (aid,)).fetchone()
        if row is None:
            continue
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM findings WHERE ticket_id=? AND severity='conflict' ORDER BY id",
            (row["id"],))]
        for i, fid in enumerate(ids):
            conn.execute("UPDATE findings SET status=? WHERE id=?",
                         ("resolved" if i < cleared else "open", fid))
        conn.execute("UPDATE tickets SET status=? WHERE id=?",
                     ("resolved" if cleared >= len(ids) and ids else "needs_review", row["id"]))

    conn.commit()

    print(f"{'stage':<14}{'act':<20}{'raised':>7}{'cleared':>9}  tint")
    for r in conn.execute(
        """SELECT COALESCE(s.name,'-') stage, a.name,
                  SUM(f.severity='conflict') raised,
                  SUM(f.severity='conflict' AND f.status!='open') cleared
           FROM tickets t JOIN artists a ON a.id=t.owner_id
           LEFT JOIN stages s ON s.id=a.stage_id
           LEFT JOIN findings f ON f.ticket_id=t.id
           WHERE t.type='rider_needs' GROUP BY t.id ORDER BY stage, a.name"""):
        raised, cleared = r["raised"] or 0, r["cleared"] or 0
        tint = "green" if raised == 0 or cleared >= raised else "yellow" if cleared == 0 else "pink"
        print(f"{r['stage']:<14}{r['name']:<20}{raised:>7}{cleared:>9}  {tint}")


if __name__ == "__main__":
    main()
