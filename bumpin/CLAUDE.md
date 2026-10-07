# BumpIn

AI-powered vendor and rider CRM for Fieldday Events' Riverside festival. Built for the Affinda AI Innovation Challenge, Track 1: Backstage.

Read this file first, then `docs/CONTRACT.md` (data model, API, function signatures, demo script). The contract is the source of truth. If you must change it, edit it in the same commit and tell the team.

## Deadline

- Stage 1 is due Thursday 8 October 2026, 5:00pm Melbourne time, on Devpost: a working prototype (link or clear run steps), a demo video up to 5 minutes, and a short description (problem, user, what we built, how AI is used, tools used).
- Target submit time: 4:30pm. Feature freeze: Thursday 12:00. Record the video 2pm to 4pm.
- Finalists pitch live on Friday 9 October at Closing Night.

## The brief (from the organisers)

Fieldday Events is a five-person company that won Riverside, a three-day riverfront festival in mid-December with up to 15,000 people a day, 60 artists, 40 food vendors and 300 volunteers. If Fieldday is not on track two weeks out, it pays a production company to take over, which would wipe it out.

Track 1 is about artist and vendor operations. Every artist sends a "rider" (stage, technical and hospitality needs) as PDFs, photos or long email threads. Every vendor sends permits, food-safety certificates and insurance. Changes and questions arrive by email and DM. The run sheet is a spreadsheet that changes daily. Problems hide between documents: a rider that does not match the stage equipment, a certificate that expires before the festival, a set time that moved and nobody told catering.

Users:

- **Ravi**, production manager. Lives in his inbox and phone, never at a desk. Uses the phone view (action cards only).
- **Jess**, founder. Uses the laptop app (full CRM view, intake, readiness, run sheet).

Success looks like: every requirement captured once, clashes found weeks out instead of on the day, artists and vendors get answers without the team chasing every detail.

## Judging (out of 100)

| Criterion | Points |
|---|---|
| Problem understanding | 15 |
| Product thinking (what we chose to build and to leave out) | 15 |
| Use of AI (meaningful work, person in control where it matters) | 25 |
| User experience | 15 |
| Originality (go beyond the obvious chatbot or flagging dashboard) | 15 |
| Execution and communication | 15 |

## Non-negotiable principles

1. **AI reads, matches and drafts. Code does the checks.** Shortages, double-bookings, expiry comparisons and sums are plain Python or SQL, never an LLM guess.
2. **Nothing sends itself.** Every outbound email is drafted by AI and sent only when a human clicks. There is no auto-reject: the AI recommends, a human confirms.
3. **Critical fields always go to a human**, whatever the confidence: insurance, food safety, gas, permits and any expiry date.
4. **Every AI claim is traceable to its source**: exact quote, document and page, so the UI can highlight it on the PDF.
5. **Uncertain items go to Ravi's review list** instead of being filed silently.
6. **All data is fake.** Never send real email to anyone except the demo recipient address.

## Hero demo (what the video shows)

1. A rider PDF arrives. BumpIn highlights the line that needs 3 decks on a stage that only has 2, shows an AI explanation, and suggests a fix. Jess or Ravi clicks Resolve, a drafted reply appears in the outbox, a human sends it, and the inventory updates when the rider is approved.
2. A vendor's food-safety certificate expires before the festival ends. BumpIn recommends rejection with a drafted email explaining which requirement failed. A human confirms.
3. 4pm Saturday: a headliner's flight is cancelled and the set is at 9:15pm. The email becomes a help ticket with proposed actions (move the set, notify the next act, the stage crew and catering). Ravi approves from his phone and the emails are drafted and sent.
4. A vague email lands with low confidence and appears in Ravi's review list instead of being filed.

Full planted-problem list is in `docs/CONTRACT.md`.

## Scope

**Must:** inbox simulation, classification, tickets (rider needs, vendor eligibility, help), PDF highlights, cross-checks, drafted emails and outbox, approve and reject flows, inventory allocation, phone action cards, run sheet export.

**Should:** hospitality running sum against a cap, notifications, first-approval-wins between Jess and Ravi.

**Cut:** chat tab, real Gmail integration, voice or phone intake, handwriting highlights, native mobile app, multi-language intake. Mention these as next steps in the pitch.

## Architecture

- Python backend (FastAPI), SQLite, plain JSON REST API under `/api`, CORS open. No auth: the acting user is sent as header `X-User: ravi` or `X-User: jess`.
- One server for both surfaces. The laptop app and the phone page poll every 2 to 3 seconds to stay in sync. The frontend stack is chosen by the frontend team and is not specified here, so keep the API framework-agnostic.
- LLM access sits behind `backend/app/shared/llm.py` so the provider can change. Responses are cached to disk (`data/llm_cache/`) keyed by prompt hash, so the demo is repeatable and cheap. Rehearse once with the cache recording, then demo with replay.
- The classifier is a "Jev-style" decision layer: `classify(text)` returns a label from a fixed list plus a confidence. It is swappable for the real Jev model if access is ever granted. Do not claim calibrated probabilities.
- Startup loads seed data into SQLite, so a free host that resets its disk still works. `POST /api/demo/reset` reloads it.

## Repo layout

```
backend/
  app/
    main.py            # FastAPI app, CORS, routers
    db.py              # sqlite connection, schema.sql, seed loader
    shared/            # llm, classifier, outbox, rules, decisions, notifications
    artists/           # Backend A
    vendors/           # Backend B
  tests/
frontend/              # frontend team, their own stack
data/
  seed/                # json/csv seed data
  docs/                # generated fake PDFs and emails
  rules/               # yaml and md rule files
  llm_cache/
docs/CONTRACT.md
prompts/               # kickoff prompts for the two backend sessions
```

## Ownership

- **Backend A (artists):** app skeleton, `db.py` and schema, stages, inventory, festival, artists, riders, cross-checks, allocation, hospitality, help-ticket ripple, run sheet and xlsx export, plus the `/overview` and `/documents` endpoints.
- **Backend B (vendors and shared):** `shared/` modules (llm, classifier, outbox, rules, decisions, notifications), the ticket handler registry and generic `/tickets` router, inbox pipeline, vendors, eligibility checks, phone cards.
- **Frontend team:** everything under `frontend/`. They consume the API in the contract and can start from the example payloads in section 13 until the backend skeleton lands.

Work inside your own folders. Do not edit another owner's folder without messaging them.

## Conventions

- Python 3.11+, type hints, pydantic models for API bodies and LLM outputs, pytest for tests.
- Small commits, pull before pushing, short-lived branches or push small fixes to `main`.
- Secrets live in `.env` (gitignored). Commit `.env.example` with blank values: `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_CACHE`, `EMAIL_MODE` (`mock` or `demo`), `DEMO_RECIPIENT`, `SMTP_*`.
- User-facing text (drafted emails, explanations, UI copy) must not contain em dashes or en dashes. Use commas, colons or periods.
- Keep comments short and only where logic is non-obvious.

## Honest-demo notes

- All data is synthetic, including the bulk-generated 60 artists and 40 vendors. Say so in the Devpost description.
- LLM self-reported confidence is not calibrated. We add an agreement check (two runs) and always review critical fields.
- Highlights only work on PDFs with a text layer. Photos and handwriting are listed as a next step.
