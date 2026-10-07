"""Cut the vendor list down to the three that carry tickets.

The board draws one card per required certificate per vendor, so the roster
decides how much is on screen. Eight vendors came to 22 cards across five
columns, which ran off the edge. The three vendors that actually carry tickets
come to nine, and there is no four-vendor set that stays under ten — the
smallest addition, a merch stall needing insurance alone, makes it exactly ten.

Kept, and why:
  1 Marlow Catering   ticket 5, expired food-safety certificate (conflict)
  2 Smoke and Co      ticket 6, missing gas document (no document at all)
  3 Harbour Coffee Co ticket 9, load-in change (one proposed action)

Nine cards, spread over all four columns: food safety 2, public liability 3,
council permit 3, gas 1. Every card belongs to a vendor with a live ticket, so
nothing on the board is a dead end. Their documents come with them; the other
37 vendors' documents go.

`POST /api/demo/reset` reloads data/seed/vendors.json and brings all 40 back,
so run this again after any reset.
"""
import sqlite3
import pathlib

DB = pathlib.Path(__file__).resolve().parent.parent / "data" / "bumpin.db"
KEEP = (1, 2, 3)

conn = sqlite3.connect(DB)
marks = ",".join("?" * len(KEEP))

vendors_before = conn.execute("SELECT COUNT(*) FROM vendors").fetchone()[0]
docs_before = conn.execute(
    "SELECT COUNT(*) FROM documents WHERE owner_type = 'vendor'").fetchone()[0]

# Documents first: they point at the vendors.
conn.execute(
    f"DELETE FROM documents WHERE owner_type = 'vendor' AND owner_id NOT IN ({marks})", KEEP)
conn.execute(f"DELETE FROM vendors WHERE id NOT IN ({marks})", KEEP)
conn.commit()

vendors_after = conn.execute("SELECT COUNT(*) FROM vendors").fetchone()[0]
docs_after = conn.execute(
    "SELECT COUNT(*) FROM documents WHERE owner_type = 'vendor'").fetchone()[0]

# Every ticket must still have its owner, or the detail screens 404.
orphans = conn.execute(
    """SELECT t.id FROM tickets t WHERE t.owner_type = 'vendor'
       AND t.owner_id NOT IN (SELECT id FROM vendors)""").fetchall()
conn.close()

print(f"vendors   {vendors_before:>3} -> {vendors_after}")
print(f"documents {docs_before:>3} -> {docs_after}")
print(f"orphaned vendor tickets: {[o[0] for o in orphans] or 'none'}")
