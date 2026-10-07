"""Put the demo back to the state before Ravi has uploaded an equipment manifest.

The seed ships a 16-item inventory for three stages, which makes the Equipment
screen look like the venue list was already filed. It wasn't: in the story the
manifest is one of the files Ravi drops on /upload, and the stats it feeds are
supposed to appear as a RESULT of that upload. So the demo starts with no
inventory and no reservations against it.

Nothing else is touched. Rider lines stay in `rider_items` — those were parsed
from rider PDFs, which genuinely have arrived — and their `inventory_item_id`
is left as it is: the one query that joins the two tables is an INNER JOIN
(backend/app/artists/tickets.py), so with the item rows gone it simply matches
nothing instead of failing.

`POST /api/demo/reset` reloads data/seed/inventory_items.json and brings all 16
items back, so run this again after any reset.
"""
import sqlite3
import pathlib

DB = pathlib.Path(__file__).resolve().parent.parent / "data" / "bumpin.db"

conn = sqlite3.connect(DB)
before = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
          for t in ("inventory_items", "allocations")}

# Allocations first: they reference the items.
conn.execute("DELETE FROM allocations")
conn.execute("DELETE FROM inventory_items")
conn.commit()

after = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
         for t in ("inventory_items", "allocations")}
conn.close()

for t in before:
    print(f"{t:<17}{before[t]:>4} -> {after[t]}")
