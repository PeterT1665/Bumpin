# Running the BumpIn demo

Everything below assumes you are in this `bumpin/` folder.

## Start it

Two processes, two terminals. Both have to be running.

```bash
# terminal 1 — backend on :8000
.venv/bin/uvicorn backend.app.main:app --port 8000 --reload

# terminal 2 — frontend on :5173
cd frontend && npm install && npm run dev
```

**On a fresh clone, run `./scripts/demo-reset` once after the first start.**
`data/bumpin.db` is not in the repository, so the backend builds an empty one
from `data/seed/` the first time it runs, and that seed is not the demo. The
reset below is what puts the demo data in place.

Open <http://localhost:5173>. If the dashboard is full of numbers, both halves are
talking to each other. If every card reads zero or "could not be loaded", the
backend is not up — check terminal 1 before anything else.

There is no login. The app acts as a single operator, `ravi`, sent on every
request as an `X-User` header.

## Reset between run-throughs

```bash
./scripts/demo-reset
```

Run it before every rehearsal and before the real thing.

This matters more than it sounds. Several buttons in the UI are **real writes
with no undo**: Resolve and Ignore on a rider conflict, Approve, Deny and Reject
on a vendor ticket, Send on a drafted email, and the add and remove controls on
the Run sheet and Equipment screens. Approving Harbour Coffee Co's load-in move
really does rewrite that vendor's load-in window and put an email in the outbox,
and it will still be rewritten the next time you open the app. Resetting takes
about a second, needs no restart, and prints what it restored so you can see it
worked.

If you have deliberately changed the data and want that to be the new starting
point, `./scripts/demo-snapshot` freezes the current state as what `demo-reset`
returns to. Only run it when the app is in a state you are happy to start from.

## The walk-through

The story is one festival, Riverside, 11 to 13 December 2026, run by one
operator. Five screens, in this order.

**Upload** (`/upload`). Drag files in; they appear immediately as cards, sorted
into Festival brief, Equipment lists, Policies and rules, Rider documents,
Vendor documents. Four files to drag live in the `Focus` folder on the desktop:
`riverside_festival_brief.pdf`, `riverside_equipment_manifest.csv`,
`riverside_hospitality_policy.csv`, `riverside_vendor_requirements.csv`. They
land in four different buckets, which is the point of the beat — Bumpin names
each file without being told. Any file type is accepted, up to 25 MB.

This screen is **visual only**. There is no upload endpoint on the backend; the
cards are held in the browser and survive navigation through localStorage.
Dropping files does not change any of the other screens. Do not promise that it
does.

**Dashboard** (`/`). Intake over the week, hospitality spend against cap,
readiness across every supplier. All of it is real, computed from the database.

**Rider needs** (`/riders`). The board of artist tickets. Each card's bar is
conflicts raised versus conflicts dealt with, and the card's tint follows it.
Open **Dj Nova**, the first card — that is the one the demo is built around.

Dj Nova sent two documents and there is a conflict on each. The strip at the
bottom of the document pane steps between them.

- The handwritten page: 4x Pioneer CDJ-3000 highlighted pink against a Dome
  Stage that owns 2, and the 2x booth monitors in yellow, which the stage can
  just cover with nothing spare.
- The typed addendum: 6x Shure SM58 against the 4 the stage has.

Hover a highlight and Bumpin's card appears beside it. Resolve opens the drafted
email; you can edit it before sending, or close the panel without sending. The
rail on the right reads 14 requirements, 2 conflicts, 12 clean, and Bumpin's
reading changes depending on which of the two documents you are looking at.

**Vendors** (`/vendors`). Three vendors.

- **Marlow Catering** — a food safety certificate that expires 5 December, six
  days before the festival ends.
- **Smoke and Co** — an email promising a gas certificate that never arrived.
- **Harbour Coffee Co** — the change ticket. It asks to move its load-in from
  07:00 to 05:30, and Bumpin lists the three consequences of saying yes: the
  move itself, a notice to the Lawn gate crew, and a notice to Smoke and Co as
  the next stall on that gate. Each is approved or denied on its own.

Approving the move writes straight through to the Run sheet, which is the
strongest thing to show here: approve it, then open the Run sheet and the
05:30 row is already there. **Reset afterwards.**

**Run sheet** (`/runsheet`) and **Equipment** (`/equipment`). Sets and load-ins
in one order; stock with reserved and free. Both take new rows from the button
beside the filters, and both have a `−` at the end of each row to take one back
off. The endpoint refuses anything an approved rider is standing on, and says
why — try removing DI box to see it. Vendor load-in rows have no `−`, because
that window belongs to the vendor record and moves by approving the vendor's
ticket.

## What is real and what is not

Worth knowing before someone asks a pointed question.

- **Conflict detection is deterministic Python**, not a model. It compares what
  a rider asks for against what the stage owns. That is a feature, not an
  apology: it cannot hallucinate a shortage.
- **The language model is off.** There is no API key configured, so document
  classification falls back to a heuristic and the drafted emails come from
  templates. Nothing on screen depends on a network call to a provider.
- **OCR is local** (RapidOCR), cached by file hash under `data/llm_cache/`.
- **The Dj Nova ticket is scripted.** Its wording, its highlight boxes and its
  requirement count are hardcoded in `frontend/src/screens/riders/djNova.ts`,
  because the handwriting parser under-reads that page. Everything else on the
  riders board is computed.
- **Upload stores nothing**, as above.

## If something looks wrong

| What you see | What it is |
| --- | --- |
| Every card reads zero | The backend is down. Restart terminal 1. |
| Requests hang rather than fail | The backend has wedged on a database lock. Ctrl-C it and start it again; the data is fine. |
| A highlight is faint and does nothing | Its finding has been resolved or ignored. Settled highlights stay on the page greyed out rather than vanishing. `./scripts/demo-reset`. |
| The run sheet shows a 05:30 Harbour row | Somebody approved the load-in move. `./scripts/demo-reset`. |
| A document pane is a black rectangle | Chrome is still rendering the PDF. Give it a second. |
