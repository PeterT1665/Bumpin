# BumpIn frontend

Vite + React + TypeScript. This is the foundation only — the shell, the tokens,
the API client and the primitives. No screen is built yet; every route renders a
placeholder.

## Run it

Needs Node 20.16 or newer. **Vite is pinned to 6.x** — Vite 7 requires Node
20.19+ and will not install here.

```bash
cd bumpin/frontend
npm install
npm run dev          # http://localhost:5173
```

The backend must be running on `:8000` in another terminal:

```bash
cd bumpin
.venv/bin/uvicorn backend.app.main:app --reload
```

Vite proxies everything under `/api` to it, so the app uses same-origin relative
URLs and never touches CORS.

| Script | What it does |
|---|---|
| `npm run dev` | dev server with HMR |
| `npm run build` | typecheck then production build |
| `npm run typecheck` | types only |
| `npm run gen:api` | see the caveat below |

## What is here

```
src/
  styles/tokens.css        every colour and text style, generated from Figma
  styles/base.css          reset
  api/types.ts             domain types, hand-written from docs/CONTRACT.md
  api/client.ts            typed fetch wrapper + ApiError
  components/AppShell.tsx  backdrop / window / rail / canvas, plus TopBar
  components/NavRail.tsx   the six destinations and their icons
  components/primitives/   Card, StatusPill, Chip, Stat, Button, FilterPill,
                           EmptyState, Table, Row
  screens/<slice>/         one folder per build slice, currently stubs
  routes/index.tsx         the router
```

### Tokens come from Figma, not from taste

`tokens.css` is generated from the colour variables and text styles in Figma
file `7NlXeHdubRDwYnkxyXotvO`. If a value changes there, change it here and
nowhere else. Do not hardcode a colour or a font size in a component.

Two rules the design enforces that are easy to break by accident:

- **There is no red.** Conflict severity is carried by `--accent-pink`, used as
  a soft fill with dark text, never as a text colour. `severityTone()` in the
  primitives maps severity to the right tone.
- **The chrome is fixed.** Rail 72px, window inset 56px, table row pitch 64px,
  card padding 28px. These are variables; use them.

### The API client assumes one operator

This build has no user switch. `ACTOR` is `'ravi'` and goes out as `X-User` on
every request. The backend still enforces first-approval-wins and will return
409 with `decided_by` / `decided_at`; `ApiError.isAlreadyDecided` and
`ApiError.isBlockedByConflict` distinguish that from an approve refused because
a conflict is still open.

One behaviour worth knowing before building any ticket screen: **approving an
action writes the change immediately and drafts an email; it does not send.**
Anything schedule-shaped must refetch after an approve.

### Why the types are hand-written

Every backend handler returns a bare `dict`, so FastAPI's `/openapi.json` has no
response shapes — generated types would all be `Record<string, unknown>`. The
`gen:api` script and the `openapi-typescript` dependency are kept for the day
the backend adds Pydantic response models, which would make this file
disposable. Until then `src/api/types.ts` is maintained by hand against
`docs/CONTRACT.md` sections 2, 3, 7 and 13.

## Building a screen

Each slice owns its own folder under `src/screens/` and shares nothing but
`components/` and `api/`. Add the route in `routes/index.tsx`. If something you
need is used on more than one screen, promote it into `components/primitives/`;
if it is used on exactly one, leave it in that screen's folder.

The designs are the Figma frames of the same name. Twelve screens, but only four
layouts: a table (Run sheet, Equipment), a board (Rider needs, Vendor progress),
a document split (Ticket detail, Change ticket, Vendor detail), and a drop zone
(Upload, Files uploaded).
