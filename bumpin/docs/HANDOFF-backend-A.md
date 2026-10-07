# Backend A handoff (artists)

For Backend B. Branch: `backend-b/shared-modules`. Everything below is pushed and 54 tests pass on the fake LLM.

## Quick start

```bash
cd bumpin
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # Python 3.11+
.venv/bin/python -m pytest -q
.venv/bin/uvicorn backend.app.main:app --reload                      # http://localhost:8000/docs
```

`openpyxl` was added to `requirements.txt` for the xlsx export.

## How to test

1. **Unit and flow tests:** `.venv/bin/python -m pytest -q`. Each check has a passing and a failing case, plus approve, reject, resolve, revised rider, ripple, highlights, run sheet and xlsx.
2. **Scenario walkthrough:** `.venv/bin/python scripts/demo_artists.py`. Runs problems 1, 2, 3 and 6 on a throwaway database and prints each ticket, finding, highlight rectangle, blocked approval, allocation and drafted email. It inserts the email rows itself, standing in for `/inbox/receive`, so it works before your pipeline lands. Once the pipeline is in, the same emails are in `data/demo/emails/*.json`.
3. **In the browser:** start uvicorn and open `http://localhost:8000/docs`. Try `POST /api/demo/reset`, `GET /api/overview`, `/api/artists`, `/api/inventory` (Halcyon holds the Moog after reset), `/api/runsheet` and `/api/export/runsheet.xlsx`. After running the walkthrough against the real database, `GET /api/documents/{id}/highlights` returns the CDJ rectangle.

The rider and help ticket flows have no HTTP route of their own yet, because `/inbox/receive` and `/tickets` are yours. When your tickets router dispatches to my handlers, the whole flow is testable over HTTP.

## What exists

| Area | Where |
|---|---|
| App, CORS, router mounting | `backend/app/main.py` |
| `X-User` dependency | `backend/app/deps.py` (`current_user`) |
| SQLite, schema, seed loader, reset | `backend/app/db.py`, `backend/app/schema.sql` |
| Your router list | `backend/app/shared/router_registry.py` (`ROUTERS = []`, yours now) |
| Artist entry points | `backend/app/artists/__init__.py` |
| Rider extraction, matching, highlights | `artists/riders.py`, `artists/ai.py` |
| Checks (plain code) | `artists/checks.py` |
| Rider tickets, approve, reject, findings | `artists/tickets.py` |
| Help tickets and ripple (problem 6) | `artists/ripple.py` |
| Run sheet and xlsx | `artists/runsheet.py` |
| Stand-ins for your modules | `artists/_compat.py` |

Seed data: `data/seed/*.json` (festival, 3 stages, 16 inventory items, 60 artists: 45 scheduled at 15 a day, 15 with status `applied` and no stage or set time). Rider PDFs in `data/docs/riders/`. Sample inbox emails for my riders in `data/demo/emails/`. Generators in `scripts/`.

## How to plug in

**Seeding vendors.** Drop `data/seed/vendors.json` (a JSON list of rows, column names as in the schema). `db.reset()` loads any `data/seed/<table>.json` automatically. For demo state that needs code, append a function to `db.POST_RESET_HOOKS`.

**Routers.** Append your `APIRouter` to `ROUTERS` in `shared/router_registry.py`. `main.py` mounts each under `/api`. Use `db.get_conn()` (commits on success) and `deps.current_user`.

**Inbox pipeline calls:**

```python
from backend.app import artists
artists.create_rider_ticket(email_id, classification)   # label rider
artists.create_help_ticket(email_id, classification)    # help_or_change from an artist
```

- Store the email row first, then each attachment as a `documents` row with `email_id` set. Any `owner_type`, `owner_id` and `kind` are fine; I set them to the matched artist and `rider`.
- If there is no attachment, I treat the email body as a pasted rider.
- I match the artist by `from_addr` against `artists.manager_email`, then by `classification.entity_hint`. No match gives a `needs_review` ticket with a `low_confidence` finding.
- I read `classification.confidence` (below 0.90 adds a low-confidence finding) and `is_major_change`.
- I do not send notifications for major changes. The routing policy in the pipeline owns that.

**Handlers.** Importing `backend.app.artists` registers `rider_needs` and `help` through `register_handler`. Methods match the `TicketHandler` protocol in the contract.

## Things I need from you

1. **`decide()` must only lock on `approve` and `reject`.** My handlers call `decide()` first for every method, as the contract says, including `resolve_finding`, `ignore_finding`, `approve_action` and `edit_action`. If those also set `decided_by`, resolving a finding would block the later approve. Audit them, do not lock on them.
2. **Map my exceptions in the tickets router:**
   - `AlreadyDecided` to 409 with `{decided_by, decided_at}` (my stand-in has `.by` and `.at`)
   - `backend.app.artists.RiderBlocked` to 409 with the message (approve while a conflict is open and no `override_reason` in the payload)
   - `KeyError` to 404
   - `ValueError` to 400 (for example a help action edited into an overlapping slot)
3. **`draft_email(ticket_id, to_addr, intent, facts)`.** I pass a finished draft in `facts["subject"]` and `facts["body"]`, plus `facts["context_used"]` (list, already includes `email_policy.md`) and `facts["actor"]`. Please use those as the draft, or let the LLM polish them while keeping the facts. My stand-in stores them as is with `status='draft'`.
4. **Approve payload.** Approve with an override is `POST /tickets/{id}/approve` with body `{"override_reason": "..."}`; please pass the body through as `payload`.
5. **Problem 6 email (yours).** From `chris@novalane.example.test`, saying the flight is cancelled and when they land, for example "We are rebooked and land at 9:40pm". The ripple then proposes Nova Lane to 22:45 and Dusk Theory forward to 21:15, then notifies the River Stage crew and catering.
6. **Vendor `site_zone`.** The catering notice goes to food and beverage vendors whose `site_zone` contains the stage's first word (for example "River Lawn Food Court" matches River Stage). With none, it goes to `catering@fieldday.example.test`.
7. **Halcyon's ticket exists after reset.** After every reset, Halcyon's rider is on file and approved by `jess`, so the shared Moog is reserved. That is why Neon Tide's rider triggers problem 2. Problem 7 (Halcyon asking to go later) will find this artist.

## Problem 7 (vague email)

- `classifier.py` now caps confidence at 0.5 for a `help_or_change` email that has hedging words ("maybe", "could we", "a bit", ...) and no clock time or firm event (cancelled, stranded, ...). Plain code, with tests in `test_classifier_vague.py`. On Groq the Halcyon email scored 0.95 before the cap and 0.5 after.
- `artists.create_help_ticket` (mine) already handles low confidence: if `classification.confidence < 0.60` or the label is `unsure`, it creates a `needs_review` help ticket with a `low_confidence` finding and **no proposed slot**. Your inbox router should still route confidence below 0.60 or `unsure` to your own needs_review ticket path, but if it calls mine, it is safe.

## Data formats the frontend sees

- `findings.bbox_json`: `{"page": 2, "page_size": [595.3, 841.9], "rects": [[x0, y0, x1, y1]], "facts": {...}}`. Points, origin top-left. Findings without a box may still have `{"facts": {...}}`.
- `tickets.proposed_actions_json` (help tickets): list of `{index, kind: "move_set" | "notify", title, detail, to_addr, artist_id, new_start, new_end, status: "proposed" | "approved", approved_by, outbox_id}`.
- `GET /api/documents/{id}/highlights`: boxes for the three input formats (PDF points, photo pixels found by OCR, email text offsets to underline), as in contract sections 10 and 13. Vendor PDFs can reuse `artists.riders.locate(doc_id, page, quote)`, which returns the same shape for all three.
- `GET /api/inventory`: each item has `aliases` (list) and `allocations` (`artist_name`, `quantity`, `start_ts`, `end_ts`).

## Without an API key

With `LLM_PROVIDER` blank or `fake`, rider extraction uses a line parser (`Nx Item` lines under Technical or Hospitality headings), and explanations use code templates. With a real provider the LLM does extraction, inventory matching fallback, wording and change parsing, and code still does every check. We plan to add the key last and record the cache in one rehearsal run.

## Notes on `llm.py`

- The Anthropic call uses `claude-sonnet-4-20250514`. The current model is `claude-sonnet-5-5`.
- The Anthropic path does not force JSON. If the reply comes wrapped in a code fence, `json.loads` fails. Worth stripping fences before parsing.
- The fake provider returns `{}` when no response is registered, which fails validation for most schemas. My code catches that and falls back.
