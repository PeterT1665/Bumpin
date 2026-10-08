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

You need **Python 3.10 or newer** and **Node.js 18 or newer**. No API key is needed: without one, BumpIn uses rule-based fallbacks and every screen still works.

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
- **Ravi's phone:** http://localhost:5173/phone (on a laptop screen it is drawn inside a phone frame)

### 5. Optional: open Ravi's view on a real phone

There is no hosted version, and a phone cannot run BumpIn itself. Instead, the laptop that runs it serves the page to your phone over Wi-Fi. `localhost` only means "this computer", so on the phone you use the laptop's network address instead.

1. Stop the app in terminal 2 (Ctrl+C) and start it again so other devices can reach it:

   ```bash
   cd frontend && npm run dev -- --host
   ```

   The backend in terminal 1 stays as it is. The phone only talks to the app, which passes requests on to the backend.

2. Find the laptop's address. Vite prints it as the `Network:` line, for example `http://192.168.1.23:5173/`. You can also look it up:
   - macOS: `ipconfig getifaddr en0`
   - Windows: `ipconfig`, then the "IPv4 Address" line
   - Linux: `hostname -I`

3. Connect the phone to the **same Wi-Fi** as the laptop and open `http://<that address>:5173/phone`, for example `http://192.168.1.23:5173/phone`. It fills the screen and refreshes on its own every few seconds.

If the page does not load:
- **Firewall prompt:** if the laptop asks whether to allow incoming connections for Node, allow it.
- **Public or university Wi-Fi:** these often block devices from reaching each other. Turn on your phone's hotspot, connect the laptop to it, and use the address the laptop gets there.
- **No phone handy:** in Chrome on the laptop, open http://localhost:5173/phone, press F12 and turn on the device toolbar (the phone and tablet icon) to see the full-screen phone layout.

---

## What to try

Reset the demo data between run-throughs (step 3).

**1. A rider that does not fit the stage.** Open *Rider needs* (second icon on the left) and pick **Sparkle**. The rider is a phone photo. Hover the pink box on "3x Pioneer CDJ-3000": the River Stage owns 2. Click **Resolve**, edit the drafted reply if you like, and click **Send**. Then use **Approve rider** in the Decision panel: while a conflict is open it asks why you are approving anyway, and once approved the rider's equipment shows as reserved on the *Equipment* screen. Try the same on **Halcyon** (a PDF).

**2. A certificate that expires too early.** Open *Vendors* and pick **Marlow Catering**. Hover "Valid until: 5 December 2026". The festival ends on 13 December. Click **Reject vendor** and give a reason.

**3. A change that ripples.** In *Vendors*, open **Harbour Coffee Co**. They want to move their load-in from 07:00 to 05:30. Hover the highlighted sentence and approve the move. Then open *Run sheet*: the 05:30 row is already there. **Download .xlsx** gives the whole sheet as a spreadsheet for the crews.

**4. 4pm Saturday, on Ravi's phone.** Open http://localhost:5173/phone (or the phone address from step 5 on a real phone), then send the headliner's email in from a terminal on the laptop:

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

**7. Send it a real email.** BumpIn can watch a real mailbox. Every new email sent to it, with its PDF or photo attachments, is classified, routed and turned into a ticket within about 15 seconds, the same as the demo emails above.

1. Make a mailbox for it. For Gmail: create a new account, turn on 2-Step Verification, then create an App Password (Google Account, Security, App passwords).
2. Add it to `bumpin/.env` and restart the backend:

   ```
   IMAP_USER=your.bumpin.mailbox@gmail.com
   IMAP_PASSWORD=the 16-character app password
   ```

3. From any address, email it as an artist's manager or a vendor, for example a subject of "Sparkle rider" with `bumpin/data/docs/riders/sparkle_rider.pdf` attached, or "Nova Lane's flight from Sydney has been cancelled, we land at 9:40pm". The ticket appears on the laptop app and the phone.

Your own address is not in BumpIn's address book, so it works out who the email is about from the artist or vendor name in it. An email that names nobody it knows goes to the review list. http://localhost:8000/api/inbox/mailbox shows when it last checked and any connection error. Replies are drafted as usual and still never sent for real.

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
- **Not built yet:** handwriting highlights, vendors who write in other languages, an outbox page listing every email, and two people deciding at once from the app (the backend already refuses a second decision).

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
