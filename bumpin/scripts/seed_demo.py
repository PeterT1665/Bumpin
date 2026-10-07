"""Feed the demo emails into the local dev backend so the screens have the planted
problems to render. Additive only: creates tickets, destroys nothing.

SEVEN OF THE NINE. Help tickets are out of the demo, so the two emails that become
one are never posted (see `SKIP`). Skipping them at the source is what makes the
chain idempotent on this: nothing is created, so nothing has to be deleted
afterwards and there is no email, document, finding or outbox row left pointing at
a ticket that is gone. Run the chain any number of times and `GET /tickets` holds
no `help` row. The two files stay on disk because they are the record of what was
cut, and putting the demo back is one edit to `SKIP`.

`make_rider_pdfs.main()` runs first. Three of those emails attach a file from that
table (Sparkle's rider, the photo of it and the typed addendum sent with the photo,
Marlow & The Lanes' rider) and `POST /inbox/receive` raises `attachment not found`
on a path that is not on disk, so the documents have to exist before the post. It is
also what keeps the PDFs on disk equal to the table that documents their quantities:
change a quantity there and the next chain run picks it up.
"""
import glob
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.make_rider_pdfs import main as build_rider_pdfs  # noqa: E402

BASE = "http://localhost:8000/api"
EMAILS = str(ROOT / "data" / "demo" / "emails" / "*.json")

#: The two emails that route to `create_help_ticket`. Nova Lane's cancellation is the
#: four-action ripple and Halcyon's one-liner is the vague-change low-confidence case;
#: both are `help` tickets, and help tickets are out of the demo.
#:
#: Dropping Nova Lane's email also leaves her set where `data/seed/artists.json` puts
#: it, Saturday 21:15 to 22:45 on the River Stage. The move to 22:45 only ever existed
#: because action 0 of that ticket was approved, so with the ticket gone the move goes
#: with it rather than standing on the run sheet with nothing to explain it. Dusk
#: Theory follows at 23:00 and nothing on the River Stage overlaps.
SKIP = {
    "06_nova_lane_flight_cancelled.json": "help ticket: Nova Lane's cancellation ripple",
    "07_halcyon_go_later.json": "help ticket: Halcyon's vague change request",
}


def post(path, body):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "X-User": "ravi"},
    )
    try:
        return json.load(urllib.request.urlopen(req, timeout=300))
    except urllib.error.HTTPError as e:
        return {"error": e.code, "body": e.read().decode()[:300]}


def count():
    return len(json.load(urllib.request.urlopen(BASE + "/tickets", timeout=60)))


print("building the rider documents the demo emails attach")
build_rider_pdfs()

print("\ntickets before:", count())
for path in sorted(glob.glob(EMAILS)):
    name = os.path.basename(path)
    if name in SKIP:
        print(f"{name:<40} SKIPPED  {SKIP[name]}")
        continue
    out = post("/inbox/receive", json.load(open(path)))
    if "error" in out:
        print(f"{name:<40} ERROR {out['error']} {out['body'][:120]}")
    else:
        print(
            f"{name:<40} ticket={out.get('ticket_id')} "
            f"{str(out.get('ticket_type')):<19}{str(out.get('ticket_status')):<13}"
            f"major={out.get('is_major_change')}"
        )
print("tickets after:", count())

helps = [t for t in json.load(urllib.request.urlopen(BASE + "/tickets", timeout=60))
         if t["type"] == "help"]
print(f"help tickets: {len(helps)}" + (f"  !! {[t['id'] for t in helps]}" if helps else "  (none, as intended)"))
