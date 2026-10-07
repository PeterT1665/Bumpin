"""Write data/seed/artists.json: 6 hand-crafted artists plus generated ones up to 60.
45 are scheduled (15 a day), the other 15 have applied and have no set time yet.

Run from bumpin/:  .venv/bin/python scripts/generate_artists.py
Generated artists get clean, non-overlapping slots and no rider problems.
Output is deterministic so the seed file stays stable in git.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "data" / "seed" / "artists.json"
TOTAL = 60  # everyone in the pipeline
PER_DAY = 15  # scheduled on the run sheet each day; the rest are status "applied" with no slot

HANDCRAFTED = [
    {"id": 1, "name": "Sparkle", "manager_name": "Sam Ortiz", "manager_email": "sam@sparkle-mgmt.example.test", "stage_id": 1, "set_start": "2026-12-11T20:00:00", "set_end": "2026-12-11T21:30:00", "status": "in_progress", "hospitality_cap": None},
    {"id": 2, "name": "Halcyon", "manager_name": "Priya Nair", "manager_email": "priya@halcyon-music.example.test", "stage_id": 2, "set_start": "2026-12-12T18:00:00", "set_end": "2026-12-12T19:15:00", "status": "in_progress", "hospitality_cap": None},
    {"id": 3, "name": "Neon Tide", "manager_name": "Leo Grant", "manager_email": "leo@neontide.example.test", "stage_id": 3, "set_start": "2026-12-12T18:45:00", "set_end": "2026-12-12T19:45:00", "status": "in_progress", "hospitality_cap": None},
    {"id": 4, "name": "Marlow & The Lanes", "manager_name": "Ada Brooks", "manager_email": "ada@marlowlanes.example.test", "stage_id": 2, "set_start": "2026-12-13T19:00:00", "set_end": "2026-12-13T20:15:00", "status": "in_progress", "hospitality_cap": 1200},
    {"id": 5, "name": "Nova Lane", "manager_name": "Chris Wu", "manager_email": "chris@novalane.example.test", "stage_id": 1, "set_start": "2026-12-12T21:15:00", "set_end": "2026-12-12T22:45:00", "status": "completed", "hospitality_cap": 2500},
    {"id": 6, "name": "Dusk Theory", "manager_name": "Mia Kowalski", "manager_email": "mia@dusktheory.example.test", "stage_id": 1, "set_start": "2026-12-12T23:00:00", "set_end": "2026-12-13T00:15:00", "status": "completed", "hospitality_cap": None},
]

FIRST = ["Velvet", "Golden", "Paper", "Static", "Lunar", "Wild", "Silver", "Coastal", "Hollow", "Bright",
         "Quiet", "Electric", "Amber", "Northern", "Glass", "Saltwater", "Midnight", "Copper", "Indigo", "Feral"]
SECOND = ["Harbour", "Pines", "Signal", "Rivers", "Motel", "Season", "Arcade", "Atlas", "Garden", "Machines",
          "Coast", "Tapes", "Weather", "Hearts", "Satellite", "Parade", "Orchard", "Ferns", "Lights", "Union"]
MANAGERS = ["Alex Kim", "Jordan Lee", "Taylor Reid", "Casey Ng", "Morgan Shah", "Riley Park", "Jamie Fox",
            "Drew Patel", "Quinn Hart", "Avery Cole", "Rowan Bell", "Sasha Moore"]

DAYS = ["2026-12-11", "2026-12-12", "2026-12-13"]
SET_MINUTES = 60
SLOT_STARTS = ["12:00", "13:15", "14:30", "15:45", "17:00", "18:15", "19:30", "20:45", "22:00"]


def _overlaps(stage_id: int, start: datetime, end: datetime) -> bool:
    for a in HANDCRAFTED:
        if a["stage_id"] != stage_id:
            continue
        a_start = datetime.fromisoformat(a["set_start"]) - timedelta(minutes=15)
        a_end = datetime.fromisoformat(a["set_end"]) + timedelta(minutes=15)
        if start < a_end and a_start < end:
            return True
    return False


def generate() -> list[dict]:
    rng = random.Random(2026)
    by_day: dict[str, list[tuple[int, datetime, datetime]]] = {d: [] for d in DAYS}
    for day in DAYS:
        for stage_id in (1, 2, 3):
            for hhmm in SLOT_STARTS:
                start = datetime.fromisoformat(f"{day}T{hhmm}:00")
                end = start + timedelta(minutes=SET_MINUTES)
                if not _overlaps(stage_id, start, end):
                    by_day[day].append((stage_id, start, end))
        rng.shuffle(by_day[day])

    # Top each day up to PER_DAY, counting the hand-crafted sets.
    booked = {d: sum(1 for a in HANDCRAFTED if a["set_start"].startswith(d)) for d in DAYS}
    slots = []
    for day in DAYS:
        slots += by_day[day][: PER_DAY - booked[day]]
    rng.shuffle(slots)

    taken = {a["name"] for a in HANDCRAFTED}
    artists = list(HANDCRAFTED)
    next_id = len(HANDCRAFTED) + 1
    while len(artists) < TOTAL:
        name = f"{rng.choice(FIRST)} {rng.choice(SECOND)}"
        if name in taken:
            continue
        taken.add(name)
        manager = rng.choice(MANAGERS)
        slug = name.lower().replace(" ", "")
        artist = {
            "id": next_id,
            "name": name,
            "manager_name": manager,
            "manager_email": f"{manager.split()[0].lower()}@{slug}.example.test",
            "stage_id": None,
            "set_start": None,
            "set_end": None,
            "status": "applied",
            "hospitality_cap": None,
        }
        if slots:
            stage_id, start, end = slots.pop()
            artist.update(stage_id=stage_id, set_start=start.isoformat(), set_end=end.isoformat(),
                          status="completed")
        artists.append(artist)
        next_id += 1
    return artists


def main() -> None:
    artists = generate()
    OUT.write_text(json.dumps(artists, indent=1) + "\n", encoding="utf-8")
    scheduled = sum(1 for a in artists if a["set_start"])
    print(f"wrote {len(artists)} artists to {OUT}, {scheduled} scheduled, {len(artists) - scheduled} applied")


if __name__ == "__main__":
    main()
