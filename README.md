# BumpIn

**An AI-powered rider and vendor CRM for a five-person festival team.**

Built for the Affinda AI Innovation Challenge, Track 1: Backstage.

Fieldday Events runs Riverside, a three-day riverfront festival with up to 15,000 people a day, 60 artists and 40 food vendors. Artists send riders (stage, technical and hospitality needs) as PDFs, phone photos and long email threads. Vendors send permits, food safety certificates and insurance. Problems hide between those documents: a rider that asks for more decks than the stage owns, a certificate that runs out before the festival ends, a set that moves and nobody tells catering.

BumpIn reads everything that comes in, checks it against what the festival actually has, and drafts the replies. A person makes every decision.

- **Laptop app** for Jess, the founder: rider and vendor boards, each document with its problem lines highlighted in place, the run sheet and the equipment list.
- **Phone view** for Ravi, the production manager, who is never at a desk: one list of action cards, most urgent first, each one approvable from the phone.

All people, companies and data in this project are made up.

---

## Try it (about 10 minutes)

You need **Python 3.11 or newer** and **Node.js 18 or newer**. No API key is needed: without one, BumpIn uses rule-based fallbacks and every screen still works.

### 1. Install

```bash
git clone https://github.com/PeterT1665/Bumpin.git
cd Bumpin/bumpin

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env

cd frontend && npm install && cd ..
```

On Windows, use `.venv\Scripts\pip` and `.venv\Scripts\uvicorn` in place of `.venv/bin/...`, and `copy` in place of `cp`.

### 2. Start it (two terminals, both in `Bumpin/bumpin`)

```bash
# Terminal 1: the backend on port 8000
.venv/bin/uvicorn backend.app.main:app --port 8000
```

```bash
# Terminal 2: the app on port 5173
cd frontend && npm run dev
```

### 3. Load the demo data

```bash
curl -X POST http://localhost:8000/api/demo/reset
```

No curl? Open http://localhost:8000/docs, find `POST /api/demo/reset` and press "Try it out", then "Execute". Run this again any time to put everything back. Most buttons in the app make real changes.

### 4. Open it

- **Laptop app:** http://localhost:5173
- **Ravi's phone:** http://localhost:5173/phone (drawn as a phone on a laptop screen, full screen on a real phone)

---

## What to try

Reset the demo data between run-throughs (step 3).

**1. A rider that does not fit the stage.** Open *Rider needs* (second icon on the left) and pick **Sparkle**. The rider is a phone photo. Hover the pink box on "3x Pioneer CDJ-3000": the River Stage owns 2. Click **Resolve**, edit the drafted reply if you like, and click **Send**. Try the same on **Halcyon** (a PDF).

**2. A certificate that expires too early.** Open *Vendors* and pick **Marlow Catering**. Hover "Valid until: 5 December 2026". The festival ends on 13 December. Click **Reject vendor** and give a reason.

**3. A change that ripples.** In *Vendors*, open **Harbour Coffee Co**. They want to move their load-in from 07:00 to 05:30. Hover the highlighted sentence and approve the move. Then open *Run sheet*: the 05:30 row is already there.

**4. 4pm Saturday, on Ravi's phone.** Open http://localhost:5173/phone, then send the headliner's email in from a terminal:

```bash
curl -X POST http://localhost:8000/api/inbox/receive \
  -H "Content-Type: application/json" \
  -d @data/demo/emails/06_nova_lane_flight_cancelled.json
```

Within a few seconds a card appears: Nova Lane's flight is cancelled and their set is at 21:15. Tap it. BumpIn proposes swapping them with the next act, telling both managers, the stage crew and the caterers near that stage. Approve each step (or **Approve all**), then send the drafted emails. The run sheet now shows the new times.

**5. When BumpIn is not sure.** Send in a vague email:

```bash
curl -X POST http://localhost:8000/api/inbox/receive \
  -H "Content-Type: application/json" \
  -d @data/demo/emails/07_halcyon_go_later.json
```

"Could we maybe go on a bit later?" lands on the phone as **Not sure**. BumpIn does not guess a new time. It leaves the decision to Ravi.

**6. Teach it the venue.** Open *Upload* (last icon on the left) and drop in the four files from `bumpin/data/demo/initial/`. The equipment list becomes rows on the *Equipment* screen and every rider is re-checked against it. The brief and the policies are saved as BumpIn's memory, which the AI reads when it explains a problem or writes a reply. For a before and after, first run `.venv/bin/python scripts/clear_inventory.py` to empty the equipment list.

The other emails in `data/demo/emails/` can be sent the same way.

---

## How the AI is used, and where people stay in control

| The AI does | Plain code does | A person does |
|---|---|---|
| Reads riders and certificates (PDF text, OCR for photos, email bodies) into structured lines, each with the exact quote it came from | Counts equipment, checks set-time overlaps, adds up hospitality costs, compares expiry dates with the festival dates | Resolves, ignores, approves or rejects every finding and ticket |
| Classifies each incoming email and says how sure it is (two independent passes; if they disagree, confidence drops) | Decides routing: low confidence, vague requests and anything about insurance, food safety, gas, permits or expiry always go to a person | Sends every email. Nothing sends itself |
| Works out what a schedule change breaks and proposes each fix as its own step | Checks a proposed slot does not overlap another set | Approves or denies each step on its own |
| Words explanations and replies, using the files uploaded as memory | Keeps an AI-worded email only if every number and time from the template survived | Can edit any draft before sending |

Every highlight points to the exact line in the original document, so a claim can always be checked. Confidence scores come from the model and are not calibrated, which is why vague and safety-critical items always go to a person.

### Running with an AI key

Edit `bumpin/.env`:

```
LLM_PROVIDER=groq          # or openai, anthropic
LLM_API_KEY=your-key
LLM_CACHE=on
```

Restart the backend. With `LLM_CACHE=on` every AI answer is saved under `data/llm_cache/`, so a second run is identical and free.

---

## Honest notes

- **All data is synthetic**, including the 28 demo artists and 3 hand-built vendors.
- **The Dj Nova ticket is staged.** Its handwritten page is real, but the reader cannot place every handwritten line reliably, so that ticket's highlight boxes and wording are set by hand in the app. Sparkle's photographed rider is read for real by OCR.
- **No email is really sent.** `EMAIL_MODE=mock` marks a draft as sent and nothing leaves the machine.
- **Single user.** There is no login. The app acts as Ravi.
- **Not built yet:** a real inbox connection (emails come in through the API, as above), approving a whole rider from the laptop view (it works on the phone view), a run sheet download button, handwriting highlights, and vendors who write in other languages.

---

## For developers

```bash
cd Bumpin/bumpin
.venv/bin/python -m pytest -q          # backend tests
cd frontend && npm run build           # type-check and build the app
```

- `bumpin/backend/`: FastAPI and SQLite. `app/artists/` (riders, checks, highlights, schedule changes, uploads), `app/vendors/` (eligibility), `app/shared/` (AI client, classifier, inbox, tickets, outbox, phone cards).
- `bumpin/frontend/`: React and Vite. The API is proxied from `/api` to port 8000.
- `bumpin/docs/CONTRACT.md`: data model, API and the planted demo problems.
- `bumpin/DEMO.md`: the scripted demo walk-through.
- API reference while the backend runs: http://localhost:8000/docs
