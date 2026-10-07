# Kickoff prompt: Backend A (artists)

Read `CLAUDE.md` and `docs/CONTRACT.md` fully before writing any code. They are the source of truth. If you need to change the contract, edit it in the same commit and tell me.

You are Backend A on BumpIn, a hackathon project due Thursday 5:00pm Melbourne time. You own the artist side of the Python backend plus the app skeleton. Work only inside `backend/app/artists/`, `backend/app/main.py`, `backend/app/db.py`, `backend/tests/` for your modules, and the seed files you own under `data/`. Your routes (`/overview`, `/artists`, `/inventory`, `/runsheet`, `/export`, `/documents`, `/demo/reset`) live in `backend/app/artists/routes.py`. Do not edit `backend/app/shared/` or `backend/app/vendors/`, which belong to Backend B. Ask me before touching them.

## First 20 minutes (do this first, then commit and push so Backend B can build on it)

1. FastAPI app in `main.py` with CORS open and an `X-User` header dependency (`ravi` or `jess`). It includes `artists.routes.router` plus every router in `shared/router_registry.ROUTERS`. Create `shared/router_registry.py` containing `ROUTERS = []` in this commit. This is the one allowed edit in `shared/`, and Backend B owns the file afterward.
2. `db.py` with SQLite, the schema from section 2 of the contract as `schema.sql`, an init function, and a seed loader that reads `data/seed/*.json`.
3. `POST /api/demo/reset` that drops, recreates and reseeds, and sets `festival.sim_today` to 2026-11-30.
4. A `/api/health` route, a `README` section on how to run, and `.env.example`.

## Then build, in this order

1. **Seed data.** Festival, 3 stages, about 15 inventory items (including a shared pool with 1 analog synth), 6 hand-crafted artists with set windows. A bulk generator script that creates 60 artists with clean, valid records. Generate 3 to 4 rider PDFs with a real text layer (reportlab or fpdf2) that plant problems 1, 2 and 3 from the contract, plus a messy email thread with a rider pasted inside.
2. **Rider pipeline.** `extract_rider` using the shared `complete_json` and `extract_text` (Backend B is writing them; code against the signatures in the contract and stub locally until they land). Each item carries an exact `quote` and `page`. `match_items` uses aliases first and an LLM fallback, and records `match_confidence`.
3. **Checks in plain code.** `check_shortage`, `check_double_booking` (time overlap on the shared pool), `hospitality_total` and `check_hospitality` against `data/rules/hospitality.yaml`. Create `findings` with `severity="conflict"` for real problems. Find the quote's rectangle with PyMuPDF `search_for` and store it in `bbox_json`.
4. **Ticket flows.** Expose `create_rider_ticket(email_id, classification)` for Backend B's inbox pipeline, and register a `rider_needs` handler with `shared/registry.register_handler`. Code against the `TicketHandler` protocol in section 6 of the contract, since Backend B commits the registry early; stub it locally until it lands. `approve_rider` creates `allocations` and is blocked while a conflict is open unless an override reason is given. `reject_rider` drafts a reason email through `shared/outbox.draft_email` and releases allocations. A revised rider reopens the ticket. Use `shared/decisions.decide` for first-approval-wins when it exists.
5. **Help ticket ripple (problem 6).** Expose `create_help_ticket(email_id, classification)` and register the `help` handler. `ripple_for_change` takes a cancellation or time change and returns proposed actions: move the set to a new slot, notify the next act, the stage crew and catering near that stage. Each proposed action drafts an email into the outbox when approved.
6. **Run sheet.** `GET /api/runsheet` from the database and `GET /api/export/runsheet.xlsx` with openpyxl.
7. `/api/overview`, `/api/artists`, `/api/inventory`, `/api/documents/{id}/file` and `/api/documents/{id}/highlights`. The generic `/api/tickets` endpoints belong to Backend B.

## Acceptance checks

- Planted problems 1, 2, 3 and 6 each produce the expected finding or ticket after `POST /api/demo/reset` and `POST /api/inbox/receive` with the matching email.
- Highlights return correct page and rectangles for problem 1.
- Approving a rider with an open conflict is rejected without an override.
- The xlsx export opens and matches the run sheet.
- pytest covers each check function with at least one passing and one failing case.

## Rules

- Checks, sums and overlaps are plain Python or SQL, never an LLM guess.
- Nothing sends itself. Drafts only, a human sends.
- Fake data only. Drafted emails and UI text contain no em dashes or en dashes.
- Small commits, pull before pushing, message me when a milestone lands (skeleton, seed data, rider flow, ripple, export).
- If you are blocked on a decision, ask me one specific question rather than guessing.
