# BumpIn frontend — working handoff

Everything needed to debug and fix the running app without re-deriving it.
Written 8 Oct 2026, after the five-slice build.

---

## 1. Run it

Two servers. Both were running when this was written; restart as needed.

```bash
# backend — FastAPI on :8000
cd ~/Desktop/Bumpin/bumpin
.venv/bin/uvicorn backend.app.main:app --port 8000

# frontend — Vite on :5173
cd ~/Desktop/Bumpin/bumpin/frontend
npm run dev
```

`/api` is proxied from 5173 → 8000 (see `vite.config.ts`), so the app uses
same-origin relative URLs and there is no CORS anywhere.

Health checks:
```bash
curl -s localhost:8000/api/health      # {"ok":true,"festival":"Riverside"}
curl -s localhost:5173/api/health      # same, through the proxy
```

Verification (run both before claiming anything is fixed):
```bash
cd ~/Desktop/Bumpin/bumpin/frontend
npm run typecheck
npm run build
```

**Node is 20.16, so Vite is pinned to 6.x.** Vite 7 needs Node 20.19+ and will
not install. Do not bump it.

---

## 2. Repo and ownership

Branch `frontend`, off `origin/backend-b/shared-modules`. **Uncommitted.**
Backend code lives on that branch — `main` only has the contract doc.

```
bumpin/
  backend/            FastAPI app (Peter + Suhaas)
  data/               seed JSON, demo emails, rule files, bumpin.db
  docs/CONTRACT.md    the source of truth for data model + API
  scripts/
    seed_demo.py      feeds the 9 demo emails into :8000   <- added here
    smoke_ripple.py   end-to-end ripple approval test      <- added here
  frontend/
    src/
      styles/tokens.css        generated from Figma — single source for colour/type
      styles/base.css
      api/types.ts             hand-written domain types
      api/client.ts            fetch wrapper + ApiError
      components/AppShell.tsx  backdrop/window/rail/canvas + TopBar
      components/NavRail.tsx   six destinations + icons
      components/primitives/   Card, StatusPill, Chip, Stat, StatStrip, Button,
                               FilterPill, EmptyState, Table, Row, severityTone
      screens/overview/        Overview, StatCards, TicketsCard
      screens/riders/          RiderNeeds, TicketDetail, DocumentPane, cards,
                               ResolveModal, rail, riders.ts
      screens/vendors/         VendorProgress, VendorDetail, DocumentPane,
                               ResolveModal, vendorModel
      screens/schedule/        RunSheet, Equipment, kit, derive
      screens/upload/          Upload, DropZone, FileCard, files
      routes/index.tsx         8 routes, covers all 13 Figma screens
```

Each `screens/<slice>/` folder is self-contained. Shared code is
`components/`, `api/`, `styles/`, `routes/`.

### Routes → Figma screens
| Route | Renders |
|---|---|
| `/` | Dashboard |
| `/riders` | Rider needs board (+ new-column state, + empty state) |
| `/tickets/:id` | Ticket detail when `type` is `rider_needs`/`vendor_eligibility`; Change ticket when `type` is `help` |
| `/vendors` | Vendor progress board |
| `/vendors/:id` | Vendor detail |
| `/runsheet` | Run sheet |
| `/equipment` | Equipment |
| `/upload` | Upload files (empty) / Files uploaded (populated) |

Resolve · Rider and Resolve · Vendor are modals, not routes.

---

## 3. Design source of truth

Figma file **`7NlXeHdubRDwYnkxyXotvO`**, page `0:1`. Always load the
`figma-use` skill before any `use_figma` call, and pass
`skillNames: "figma-use"`.

### Node ids
| Screen | Frame | Key children |
|---|---|---|
| Dashboard | `13:2` | rail `13:8`, Intake `26:2`, Spend `157:2`, Readiness `35:2`, tickets table `17:2` |
| Rider needs | `86:2` | canvas `86:29`, controls `87:14`, board `88:2` |
| Rider needs · New column | `111:2` | |
| Ticket detail | `118:2` | doc pane `119:2`, suggestion card `121:2`, rail `122:2`/`122:6`/`122:19` |
| Change ticket | `230:2` | doc pane `230:30`, action card `231:14`, reading `230:135`, donut `230:140`, details `230:152` |
| Resolve · Rider | `204:2` | modal `204:177` |
| Resolve · Vendor | `204:178` | modal `204:334` |
| Vendor progress | `159:2` | |
| Vendor detail | `176:2` | doc panel `176:33`, suggestion `176:65`, details `176:127` |
| Upload Files | `113:2` | canvas `113:29`, drop zone `113:35` |
| Files Uploaded | `113:43` | canvas `113:70`, grid `113:80`, card `113:81` |
| Run sheet | `212:2` | table card `214:2` |
| Equipment | `224:147` | table card `224:206` |
| Card — Change actions | `199:2` | `200:3` all proposed, `201:3` partly approved, `202:3` blocked, `203:15` edit popover |
| Empty states | `231:66` | `231:385` dashboard, `231:766` board, `231:1172` table |
| Design system | Typography `4:16`, Logo `6:2`, Logo — Oogly `13:29`, Colour `34:2` | |

### The rule that matters
**Transcribe, never infer.** A verification pass caught seven bugs in the first
foundation and every single one was a value that had been guessed rather than
read. Read `x`, `y`, `width`, `height`, `cornerRadius`, fills, strokes and
effects off the node and copy them. If you are reasoning about what a value
probably is, go read it instead.

Corollary for verification: a numeric diff catches these; a screenshot does
not. Compare the Figma node's measurements against `getBoundingClientRect` /
`getComputedStyle` in the running page.

### Hard design facts
- **There is no red anywhere.** Conflict severity is `--accent-pink` used as a
  soft fill with dark text, never as a text colour (it fails contrast at 14px).
  `severityTone()` in the primitives maps severity → tone.
- Figma uses `strokeAlign: INSIDE`, so a stated height already contains its 1px
  stroke. A real CSS `border` adds 2px and insets children. Use
  `box-shadow: inset 0 0 0 1px <colour>` instead. This bit three slices.
- Chrome measurements are fixed: rail 72, window inset 56, canvas padding 40,
  table row pitch 64, card padding 26 top / 28 sides, divider inset 28.
- Nav slot pitch is 56px; the first slot's top is y=127 (the logo ends at y=80,
  so the gap is 47, **not** 56).
- Radii: card 24, window 20, panel 18, pill 18, chip 10, backdrop 32.
- Shadows: card `0 2px 10px rgba(18,20,31,.06)`, panel `0 6px 20px rgba(18,20,31,.14)`.

### Status pill (corrected values)
h28, r14, padding `0 14px 0 12px`, gap 6, dot 5px solid `--ink-900`, label is
`t-label-sm` (Funnel Sans Medium 12). Fills are the **solid** accents, not the
soft tints: ok `--accent-green`, progress `--accent-pink`, warn
`--accent-yellow`, neutral `--surface-sunken`.

Note: the Figma file disagrees with itself on the right padding — dashboard
pills read 10, run sheet pills read 14 — because the dashboard's text boxes are
hand-sized rather than glyph-fitted. 14 is the self-consistent value.

---

## 4. API notes

`src/api/client.ts` wraps everything. `ACTOR = 'ravi'` goes out as `X-User` on
every request; there is no user switch in this build.

### Gotchas
- **Every backend handler returns a bare `dict`**, so `/openapi.json` has no
  response shapes. `src/api/types.ts` is hand-written from `docs/CONTRACT.md`
  and was corrected against live responses. `npm run gen:api` is wired but
  useless until the backend adds Pydantic response models — that is the single
  highest-value ask of the backend team.
- `GET /tickets` returns more than the contract example shows: it includes
  `owner`, `open_findings`, `owner_type`, `owner_id`, `decided_by`,
  `decided_at`. `TicketSummary` reflects this.
- **Two different 409s.** `ApiError.isAlreadyDecided` (has `decided_by`) means
  someone already decided the ticket. `ApiError.isBlockedByConflict` (no
  `decided_by`) means an approve was refused because a conflict is still open.
- **The ripple overlap refusal is a 400, not a 409.** `approve_action` raises
  `ValueError("The new slot overlaps another set. Edit the time first.")` and
  `_act` in `backend/app/shared/tickets.py` maps `ValueError → 400`. Handle any
  non-already-decided refusal as an inline row error.
- **Approving an action writes the schedule change immediately and drafts one
  email. It does not send.** The ticket goes `in_progress` after the first
  approve and only `resolved` when every action is approved. Anything
  schedule-shaped must refetch after an approve.
- `GET /documents/{id}/file` and `/export/runsheet.xlsx` return bytes — use
  `urls.documentFile(id)` / `urls.runsheetXlsx` as `src`/`href`.

### Highlights
`GET /documents/{id}/highlights` returns three shapes; origin is top-left.
- `pdf` — `rect` in PDF points + `page_size`; draw at `rect / page_size` of the
  rendered size.
- `image` — same proportional math, `rect` in image pixels.
- `text` — `start`/`end` character offsets into the text from
  `/documents/{id}/file`; underline that span.

Only `severity: "conflict"` reads as a conflict. Hide or grey entries whose
`status` is not `open`. A finding with no box shows its quote as text.

---

## 4a. Cross-screen search

`src/components/search.tsx` holds the top-bar query. The box lives in `TopBar`
(AppShell) but the lists it filters live in the screens, so the query goes
through context rather than props:

- `useSearch()` -> `{ q, setQ }`. `TopBar` is the only writer; screens read.
- `matches(q, ...fields)` — case-insensitive contains, **true when `q` is
  blank**, so a screen can call it unconditionally in a `.filter()`.
- `SearchProvider` wraps the `<Outlet />` inside the window, and clears `q` on
  every `pathname` change. A query typed on one screen must not silently hide
  rows on the next.
- Screens pass `placeholder` to `TopBar` naming what they actually search.

Two states that look alike and are not: "no rows match your search" and "there
is no data at all". Never render the screen's `EmptyState` for a search miss —
it tells the operator their festival is empty when it isn't.

The notification bell that used to sit beside the search box is gone; there is
no notification surface in the build, so the button was decorative.

## 5. Test data — which ticket exercises what

Tickets 1-9 are the nine demo emails; 10-17 are the riders
`generate_festival.py` adds to fill the board. **Ticket ids are stable** as
long as you run the chain in order.

| Ticket | Owner | Type | Exercises |
|---|---|---|---|
| 1 | Halcyon | `rider_needs` | `double_booking` with Neon Tide over the one shared Moog One |
| 2 | Sparkle | `rider_needs` | `shortage` conflict, **image highlight** (OCR photo), doc 107 |
| 3 | Neon Tide | `rider_needs` | `double_booking` conflict, **text highlight** doc 104 offsets 109–137 |
| 4 | Marlow & The Lanes | `rider_needs` | `over_budget` warning, **pdf highlight** doc 105 |
| 5 | Marlow Catering | `vendor_eligibility` | `expired_cert` conflict, **pdf highlight** doc 106 |
| 6 | Smoke and Co | `vendor_eligibility` | `missing_doc` conflict, **no document at all** |
| 7 | Nova Lane | `help` | `schedule_change` conflict, text highlight doc 109, **4 proposed actions** |
| 8 | Halcyon | `help` | `low_confidence` 0.45, text highlight doc 110, **no proposed actions** |
| 9 | Harbour Coffee Co | `vendor_eligibility` | `schedule_change`, **1 action** `move_load_in` |

Tickets 10-17 (Wild Hearts, Paper Pines, Velvet Signal, Midnight Garden,
Indigo Machines, Quiet Satellite, Coastal Rivers, Static Parade) exist to fill
the board with every tint. Their conflicts are derived the same way as the
rest: the rider asks for more than the manifest says the stage owns.

Between them these cover all three highlight renderers, both 409 kinds, the
no-document path, and the multi-action path.

### Current database state (as written)
- **17 tickets**: 12 rider, 3 vendor, 2 help. 27 artists, 3 vendors.
- Rider board tints: **4 green, 5 yellow, 3 pink**, and every stage column
  carries all three. The strip above it counts the same tally the cards are
  tinted by, so the two cannot disagree.
- **Ticket 7 action 0 is already approved**, so Nova Lane sits at
  22:45–00:15 (was 21:15–22:45) and ticket 7 is `in_progress`. Actions 1–3 are
  still `proposed`. Dusk Theory is still at 23:00.
- 5 outbox rows, all `draft`, **0 sent**.
- Tickets 10, 11 and 15 are **approved**, which is what puts 29 units into
  `allocations` and 8 items at zero free. Without them the Equipment screen
  reads all zeroes while tickets claim equipment conflicts.
- Mail is backdated across Mon-Sun so the Intake chart has no empty track.
- `readiness_pct` is **15%**, not the seed's 90%. The seed marked every
  scheduled artist `completed`, which contradicted the readiness arc on the
  same card. One statement reverts it if you ever want the old number:
  `UPDATE artists SET status = 'completed' WHERE set_start IS NOT NULL;`
- **3 vendors**, not the seed's 40 — see `scripts/trim_vendors.py`. The board
  draws one card per required certificate per vendor, so the roster decides
  how much is on screen: 8 vendors came to 22 cards, these 3 come to 9, and no
  4-vendor set stays under 10.
- The board has **4 columns**. The design's fifth, "Liquor licence", was
  declared with `kinds: []` and could never hold a card under any data.
- Highlights are **pink (conflict) and yellow (warning) only**. There is no
  blue. A field that parsed cleanly gets no box: a page where everything is
  highlighted says nothing about where to look. Several documents therefore
  carry no highlights at all, which is correct.
- Ticket 2's finding 5 is `open`. Keep it that way: it is the **only** open
  rider finding in the demo, which makes it the only place the hover card and
  the Resolve button appear at all. Verifying the resolve flow resolves it, and
  a resolved finding 5 silently removes the feature from every rider ticket.
  `scripts/restore_ticket2.py` rewinds exactly that one test — finding back to
  `open`, ticket back to `needs_review`, the drafted reply deleted, the two
  audit rows dropped. Run it after any resolve test.

### Demo data scripts

Run after any `POST /demo/reset`, in this order:

| Script | What it does |
|---|---|
| `scripts/seed_demo.py` | feeds the nine demo emails in (additive) |
| `scripts/trim_vendors.py` | 40 vendors -> 8, documents follow; keeps every ticketed vendor |
| `scripts/clear_inventory.py` | empties `inventory_items` and `allocations` |
| `scripts/enrich_highlights.py` | adds the yellow caution highlights the seed never produces |
| `scripts/restore_ticket2.py` | rewinds a resolve test on ticket 2 |
| `scripts/ingest_initial.py` | the demo's opening upload: parses `data/demo/initial/*.csv` |

### The demo's opening upload

`data/demo/initial/` holds the four files Ravi drops at the top of the demo —
the festival brief, the hospitality policy, the vendor requirements and the
equipment manifest. Only the manifest changes the database; the other three
are the backend's own rules files shipped as CSV so they can be shown being
uploaded.

`scripts/ingest_initial.py` parses the manifest into `inventory_items` and then
runs the REAL rider pipeline — `process_rider` re-extracts each rider,
re-matches every line against the new equipment, runs the shortage /
double-booking / hospitality checks and rewrites the ticket's findings. None of
the conflicts are hand-written; they fall out of the manifest meeting the
riders, which is the claim the demo makes.

Two things it has to get right, both learned the hard way:
- **Latest rider only.** An artist who sent a revised rider has both on file,
  and extracting both sums their lines — Sparkle's "3x CDJ-3000" became 6x and
  the finding moved onto the superseded document.
- **Two passes.** The double-booking check reads what OTHER artists have
  matched, so on a single pass a shared-pool clash is only visible from
  whichever side is processed last. Halcyon and Neon Tide both want the one
  Moog One; one pass flagged only Neon Tide.

Run order after a reset: `seed_demo` → `trim_vendors` → `ingest_initial` →
`enrich_highlights`. The last one must come after, because `process_rider`
deletes and rewrites every rider finding.

`enrich_highlights.py` is the one worth understanding. A highlight can only
come from a finding — the endpoint reads `findings.bbox_json` and nothing
else — so a field that parsed *correctly* still has to be stored as an `info`
finding to get a blue box. The seed only ever flags what is wrong, so every
document showed exactly one pink box and the legend's other two tones never
appeared anywhere in the product.

None of its rectangles are guessed:
- doc 107 is an OCR'd photo, and `data/llm_cache` holds one rect per line. The
  seeded conflict's bbox IS one of those rects verbatim, so the new ones are
  copied the same way.
- docs 105 and 106 are generated PDFs. Helvetica AFM widths plus two constants
  (rect height 1.375em, baseline drop 0.3008em) turn a content-stream line into
  a rect. Both constants were derived from the seeded rects and are re-checked
  against them on every run, at two different font sizes — the script aborts
  rather than insert anything if the transform stops reproducing them.

### Proposed actions are Approve / Deny

`POST /tickets/{id}/actions/{index}/deny` is the mirror of approve and
deliberately the quiet one: nothing moves on the run sheet, no reservation
shifts, no email is drafted. The action's `status` becomes `denied` and
`approved_by` records who decided. The ticket resolves once every action has
been decided EITHER way, so a denied action does not leave it open forever,
and approve now refuses any action that is not still `proposed` rather than
only refusing already-approved ones.

The per-action Edit popover is gone — the row is Approve and Deny. Editing the
EMAIL before it sends is unaffected; that is the resolve modal, and it is what
the demo script means by rewriting a reply.

### Uploads persist

There is no upload endpoint, so the Upload screen holds what was dropped and
nothing leaves the browser. It now keeps the card list in `localStorage` under
`bumpin.uploaded-files.v1` so a file you just "uploaded" is still listed after
you navigate away and come back — without it the grid emptied on every visit,
which is fatal if the demo cuts away from that screen and returns. Only the
card's own fields are stored; the `File` objects are not, because nothing reads
their bytes.

### Two standing rules

**No card outside a highlight.** Every card that carries a decision — the rider
suggestion, the help ticket's proposed actions, the vendor decision — is
revealed from a highlight and is absent from the DOM at rest. Nothing is
pinned beside the document. A finding with no box anchors to its quote mark
instead. The one exception is a document with no highlight at all, where a
card has nothing to hang off and falls back into the flow rather than becoming
unreachable.

**Those cards hold real controls**, so hover alone is not enough: clicking the
highlight, or moving focus into the card, PINS it open until Escape or an
outside click. Without that, Approve, Reject and the Edit popovers' text
inputs cannot be operated at all — the screen looks right and does nothing.

**No em dashes as headline separators.** ` · ` instead. The standalone `—`
used as an empty-value placeholder in stats and detail rows stays.

**A progress bar counts conflicts.** One segment per conflict the ticket
raised, filled `--ink-900` once that conflict is dealt with. It is a property
of the TICKET, not of a document — a ticket can raise conflicts across several
documents, so every vendor card for the same vendor shows the same bar.
`ignored` counts as dealt with: it is a decision about the conflict, and the
bar is about open versus closed, not which way it closed. No conflicts means no
denominator, so **no track is drawn at all** — an empty track reads as "none of
them done", which is a different statement. This holds in three places: the
overview table, the rider board and the vendor board. `GET /tickets` cannot
answer it (`open_findings` is a count of every open finding, any severity), so
each of those screens makes a second pass over `GET /tickets/{id}`.

### Two traps around highlights

A highlight box sits ON TOP of the rendered page. An opaque fill therefore
hides the line it points at — invisible with one box per page, fatal once a
page has eight. Both panes now set `mix-blend-mode: multiply` on the box, with
`isolation: isolate` on the page so the blend stays inside it. If you ever add
a third document pane, it needs the same thing.

`VendorDetail` must pass only the findings the OPEN document can show —
`shown`, which is this document's findings plus the ones with no document at
all. A finding belonging to one of the vendor's other documents has no
highlight on this page to anchor to, so it falls back into the flow, and
passing all of them puts a stack of unrelated cards under the page. That stack
is the bug the hover anchoring was built to remove.

### Inventory starts empty

`scripts/clear_inventory.py` empties `inventory_items` and `allocations`. The
seed ships 16 items across the three stages, which makes the Equipment screen
look like the venue manifest was already filed — but in the story the manifest
is one of the files Ravi drops on `/upload`, and the numbers it feeds are
supposed to appear *because of* that upload. So the demo opens with no
inventory and the Equipment screen on its empty state.

`POST /demo/reset` reloads the seed and brings all 16 back, so run the script
again after any reset. Rider lines in `rider_items` are left alone: the only
query joining them to inventory is an INNER JOIN, so with no item rows it
matches nothing rather than failing.

### Reset and reseed
```bash
cd ~/Desktop/Bumpin/bumpin
curl -s -X POST -H 'X-User: ravi' localhost:8000/api/demo/reset   # wipes back to 1 ticket
.venv/bin/python scripts/seed_demo.py                              # recreates tickets 2–9
.venv/bin/python scripts/smoke_ripple.py                           # end-to-end ripple check
```
`demo/reset` rebuilds everything from `data/seed/*.json` and drops you back to a
single ticket, so **always reseed after resetting** or every screen looks empty.

---

## 6. Backend gaps — things the UI renders empty on purpose

None of these are frontend bugs. Each renders the real structure with the empty
treatment rather than inventing data.

**Blocks the upload story entirely**
1. No multipart upload endpoint. `POST /inbox/receive` takes file *paths* that
   must already exist on disk and only ever writes `documents` rows.
2. `python-multipart` is not in `requirements.txt`, so FastAPI cannot parse a
   form at all until it is added.
3. No spreadsheet parser mapping rows into `inventory_items`/`artists`/`vendors`.
4. `.xls` was dropped from the supported formats because `openpyxl` reads only
   `.xlsx`/`.xlsm`. Add `xlrd>=2.0` if it must come back. The Figma copy at
   `113:42` still advertises `.xls`.
5. **Ordering constraint:** riders uploaded before an equipment manifest produce
   *silently* zero findings — `check_double_booking` JOINs `inventory_items` and
   returns nothing, `check_shortage` falls through to `low_confidence` for every
   line. The upload screen surfaces this; the backend does not enforce it.

**Three dashboard cards have no endpoint**
6. Intake — needs an outcome bucket on `emails` (clean/flagged/clash) plus
   `GET /overview/intake`.
7. Hospitality spend — needs a spend-category column; `rider_items.category` is
   only `technical`/`hospitality`, the design's four categories do not exist.
8. Readiness — `/overview` returns only `readiness_pct`; the five-way split has
   no source.

**Four columns render empty**
9. Ticket progress + `%` — no completion field on `tickets`.
10. Run sheet `Needs` — `rider_items` is not exposed per row. Partially derived
    from `/inventory` allocations, which only covers already-approved riders.
11. Run sheet `Changed` + "changed today" — nothing records that a row moved.
    `audit_log` writes `action_approved` with a title and timestamp, so an
    endpoint over it would fill this.
12. Equipment `Flag` — findings are not joined to `inventory_item_id`, so
    unmet rider demand cannot be attributed to an item.

**Smaller**
13. No email address on `/tickets` rows (the design's second source line).
14. No ticket sub-kind (`Rider · Technical`, `Vendor · Insurance`).
15. `Verified` / `Expiring` / `Overdue` have no `TicketStatus` equivalent.
16. No `liquor` in `documents.kind`, so the Liquor licence column cannot map.
17. No day filter on `/runsheet` — the Fri/Sat/Sun tabs filter client-side.
18. No stage-create endpoint, so the board's new column is screen-local state.

---

## 7. Known open items

- **Hospitality spend card has no border and no shadow in Figma** while its
  three neighbours do. Verified by pixel sampling, transcribed as-is, but it
  looks like a slip in the design file. Needs a decision.
- Several slices duplicate a document pane and a panel surface rather than
  importing across folders (they were built in parallel). Promotion candidates:
  `DocumentPane`, the inset-stroke `Panel`, the pages/documents strip, the
  donut, the suggestion card, `CountBadge`, `FilterTab` (84×32 r16 — distinct
  from the existing 36px `FilterPill`).
- `EmptyState`'s geometry was corrected but two slices still carry local copies
  (`TableEmpty` in schedule's `kit.tsx`); they can collapse back now.
- Equipment's "Fully booked" stat uses a green rule, which reads oddly for a
  constraint. Cosmetic.

---

## 8. Debugging checklist

1. Is the backend up? `curl -s localhost:8000/api/health`
2. Is the data seeded? `curl -s localhost:8000/api/tickets | python3 -c 'import json,sys;print(len(json.load(sys.stdin)))'` — should be 9, not 1.
3. Does it typecheck and build? Both, not just one.
4. Is the value wrong, or inferred? Read the Figma node before changing a number.
5. Is it a frontend bug or a backend gap? Check section 6 first — twelve
   deliberately-empty surfaces live there.
6. Console: only React Router future-flag warnings should appear, and those are
   now opted into. Anything else is real.
