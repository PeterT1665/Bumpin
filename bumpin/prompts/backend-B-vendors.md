# Kickoff prompt: Backend B (vendors and shared)

Read `CLAUDE.md` and `docs/CONTRACT.md` fully before writing any code. They are the source of truth. If you need to change the contract, edit it in the same commit and tell me.

You are Backend B on BumpIn, a hackathon project due Thursday 5:00pm Melbourne time. You own the vendor side plus the shared modules that both backends use. Work only inside `backend/app/shared/`, `backend/app/vendors/`, the tests for those, and the seed and rule files you own under `data/`. Backend A owns `main.py`, `db.py` and `backend/app/artists/`. Do not edit those; ask me. Backend A commits the app skeleton and schema in about 20 minutes. Until it lands, start with the shared modules below, which do not depend on it.

## Start now (no dependencies)

1. `shared/llm.py`: provider-agnostic client read from `.env` (`LLM_PROVIDER`, `LLM_API_KEY`). Provide `complete_json(prompt, schema, cache_key=None)` returning a validated pydantic model, and `extract_text(path)` returning text per page (PyMuPDF for PDFs, vision LLM fallback for images). Cache responses to `data/llm_cache/` keyed by prompt hash when `LLM_CACHE=on`, so the demo is repeatable and cheap. Provide a fake provider for tests.
2. `shared/classifier.py`: `classify(text) -> Classification` exactly as in section 5 of the contract. Run two independent enum-constrained calls, lower the confidence to at most 0.5 if the labels differ, and return `is_major_change`. Write 12 fake emails covering rider, vendor document, help or change, and ambiguous cases (include "Could we maybe go on a bit later?"), and unit tests over them.
3. `shared/rules.py`: loaders for `data/rules/*.yaml` and `*.md`.

## After Backend A's skeleton lands

4. `shared/outbox.py`: `draft_email`, `update_draft`, `send`. Drafting prompts always load `data/rules/email_policy.md` and record `context_used` (the entities and files the AI read). `send` supports `EMAIL_MODE=mock` (mark as sent, no network) and `demo` (also deliver to `DEMO_RECIPIENT` only, never to the real artist or vendor address).
5. `shared/decisions.py`: `decide(ticket_id, actor, action, payload)` with first-decision-wins. A later attempt raises `AlreadyDecided` and the API returns 409 with who and when. Write every decision to `audit_log`. `shared/notifications.py`: `notify(for_user, ticket_id, text)` and the notification endpoints.
6. **Handler registry and tickets router.** Commit this right after Backend A's skeleton lands, because Backend A registers against it. `shared/registry.py` with the `TicketHandler` protocol and `register_handler` exactly as in section 6 of the contract. `shared/tickets.py` with the generic endpoints (`/api/tickets`, ticket detail, finding ignore and resolve, approve, reject, action approve and edit) that look up the handler by `ticket.type` and call it. Append the router to `shared/router_registry.py`.
7. **Inbox pipeline.** `POST /api/inbox/receive`: store the email and attachments, extract text, classify, then route by label and sender role: `rider` calls `artists.create_rider_ticket`, `vendor_doc` calls `vendors.create_vendor_ticket`, `help_or_change` calls `artists.create_help_ticket` for artists or `vendors.create_vendor_change_ticket` for vendors, and `unsure` creates a `needs_review` ticket. Code against these signatures and stub them until Backend A's side lands. Apply the routing policy in the contract (confidence bands, critical fields always reviewed, major change inside the two-week window notifies Ravi immediately).
8. **Vendors.** Seed 8 hand-crafted vendors and a bulk generator for 40, each with `site_zone`, `load_in_start` and `load_in_end`, with generated certificate and permit PDFs (reportlab or fpdf2, real text layer) and emails planting problems 4 and 5, plus the vendor change email for problem 8 (Harbour Coffee Co moves its load-in from Friday 07:00 to Friday 05:30, which creates a `schedule_change` finding and a Ravi card; `load_in_start` only changes after a human approves). `extract_vendor_doc` returns kind, expiry date, issuer, quote and page. `check_eligibility` compares against `data/rules/vendor_eligibility.yaml` in plain code (missing documents per vendor type, expiry before festival end, gas certificate when `uses_gas`). Create findings with quote and bbox. `recommend_rejection` drafts an email explaining which requirement failed and never sends it. A human confirms through the approve and reject endpoints. Expose `create_vendor_ticket(email_id, classification)` and `create_vendor_change_ticket(email_id, classification)` for the inbox pipeline, and register a `vendor_eligibility` handler.
9. **Phone cards.** `GET /api/phone/cards?user=ravi` returns a most-urgent-first list of needs-review items, major changes and pending approvals, each with a one-line summary, the source snippet and the allowed actions.
10. Write `data/rules/vendor_eligibility.yaml`, `email_policy.md` and your entries in `actions.yaml`.

## Acceptance checks

- Problems 4, 5, 7 and 8 behave as the contract's table says after `POST /api/demo/reset` and the matching `POST /api/inbox/receive`.
- The ambiguous email lands in Ravi's review list with low confidence and never files itself.
- Critical-field findings always need review, even at confidence 0.99.
- A second decision on the same ticket returns 409 with the first decider.
- Drafted rejection emails name the exact requirement and the vendor's expiry date.
- pytest covers the classifier cases, the eligibility checks and `decide`.

## Rules

- Checks and date comparisons are plain Python, never an LLM guess.
- Nothing sends itself. Drafts only, a human sends, and real delivery goes only to the demo recipient.
- Fake data only. Drafted emails and UI text contain no em dashes or en dashes.
- Small commits, pull before pushing, message me when a milestone lands (shared modules, pipeline, vendors, phone cards).
- If you are blocked on a decision, ask me one specific question rather than guessing.
