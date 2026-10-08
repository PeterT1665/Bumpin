"""Backend A routes: /overview, /artists, /stages, /inventory, /runsheet, /export, /documents, /demo/reset."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response

from backend.app import db
from backend.app.artists import demo, riders, uploads
from backend.app.artists._compat import audit
from backend.app.artists.models import RunsheetRow
# `_day` is private, but the label it builds IS the Run sheet's day tab. Formatting the
# same date a second time here would let the two spellings drift and file a new row under
# a fourth tab on a three-day festival.
from backend.app.artists.runsheet import _day, build_runsheet, runsheet_xlsx
from backend.app.deps import current_user

router = APIRouter()

if demo.after_reset not in db.POST_RESET_HOOKS:
    db.POST_RESET_HOOKS.insert(0, demo.after_reset)


@router.post("/demo/reset")
def demo_reset(user: str = Depends(current_user)) -> dict:
    """Put the demo back to its starting state.

    On the live database this restores data/demo_baseline.db, the same thing
    ./scripts/demo-reset does, so it works without bash or the sqlite3 tool.
    Anywhere else (tests, a fresh database elsewhere) it rebuilds from data/seed."""
    baseline = db.DATA_DIR / "demo_baseline.db"
    if baseline.exists() and db.DB_PATH.resolve() == (db.DATA_DIR / "bumpin.db").resolve():
        src = sqlite3.connect(baseline)
        with db.get_conn() as dst:
            src.backup(dst)
        src.close()
        # The snapshot predates newer tables (memory, mailbox_seen); put them back.
        with db.get_conn() as conn:
            db.init_schema(conn)
        with db.get_conn() as conn:
            counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                      for t in ("artists", "vendors", "tickets", "findings", "inventory_items")}
        return {"ok": True, "source": "demo_baseline.db", "counts": counts, "by": user}
    counts = db.reset()
    return {"ok": True, "source": "seed", "sim_today": db.SIM_TODAY, "counts": counts, "by": user}


@router.get("/overview")
def overview() -> dict:
    with db.get_conn() as conn:
        fest = db.row(conn.execute("SELECT * FROM festival LIMIT 1")) or {}
        count = lambda sql, *a: conn.execute(sql, a).fetchone()[0]  # noqa: E731
        artists_total = count("SELECT COUNT(*) FROM artists")
        artists_scheduled = count("SELECT COUNT(*) FROM artists WHERE set_start IS NOT NULL")
        artists_ready = count("SELECT COUNT(*) FROM artists WHERE set_start IS NOT NULL AND status = 'completed'")
        vendors_total = count("SELECT COUNT(*) FROM vendors")
        vendors_ready = count("SELECT COUNT(*) FROM vendors WHERE status = 'completed'")
        return {
            "festival": fest,
            "suppliers": {
                "artists": artists_total, "artists_scheduled": artists_scheduled,
                "artists_applied": artists_total - artists_scheduled, "artists_ready": artists_ready,
                "vendors": vendors_total, "vendors_ready": vendors_ready,
            },
            "readiness_pct": round(100 * (artists_ready + vendors_ready) / max(artists_scheduled + vendors_total, 1)),
            "documents": count("SELECT COUNT(*) FROM documents"),
            "needing_attention": count("SELECT COUNT(*) FROM tickets WHERE status IN ('open', 'needs_review')"),
            "expiring_soon": count(
                "SELECT COUNT(*) FROM documents WHERE expiry_date IS NOT NULL AND expiry_date < ?",
                fest.get("end_date", "9999")),
            "open_conflicts": count("SELECT COUNT(*) FROM findings WHERE status = 'open' AND severity = 'conflict'"),
            "intake": _intake(conn),
            "hospitality": _hospitality(conn),
            "readiness": _readiness(conn),
        }


# --- dashboard breakdowns -------------------------------------------------------------
# The three cards on 13:2 each want a shape `/overview` did not serve, so each was
# rendering its empty specimen. All three are derivable from tables already here.

#: Figma 26:2 draws seven day tracks.
_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _intake(conn) -> list[dict]:
    """Mail per weekday, split by what it turned into: a clash (some conflict),
    something flagged (a warning) or a clean parse. One entry per track."""
    rows = db.rows(conn.execute(
        """SELECT e.received_at,
                  MAX(CASE WHEN f.severity = 'conflict' THEN 2
                           WHEN f.severity = 'warning'  THEN 1 ELSE 0 END) AS worst
           FROM emails e
           LEFT JOIN findings f ON f.ticket_id = e.ticket_id
           WHERE e.direction = 'in'
           GROUP BY e.id"""))
    buckets = {d: {"day": d, "clean": 0, "flagged": 0, "clash": 0} for d in _DAYS}
    for r in rows:
        try:
            weekday = date.fromisoformat(r["received_at"][:10]).weekday()
        except ValueError:
            continue
        b = buckets[_DAYS[weekday]]
        b[("clean", "flagged", "clash")[r["worst"] or 0]] += 1
    return list(buckets.values())


#: Which hospitality item lands in which row of 231:687.
#:
#: An earlier cut sent every non-hospitality rider line to a "Backline" row,
#: which could only ever read $0: `rider_items.unit_cost` is set on hospitality
#: lines and nothing else, so that row had no dollars to show and had to be
#: drawn in grey as a line count. A card titled "Hospitality spend" with one
#: row measured in a different unit is the card contradicting itself. The four
#: rows are now four slices of the same priced thing, so every one carries
#: dollars and the whole chart reads on one scale.
_SPEND_ROWS = {
    "Catering": ("meal", "platter", "sushi", "cheese", "fruit", "snack", "food"),
    "Drinks": ("beer", "champagne", "prosecco", "water", "soft drink", "wine", "juice"),
    "Dressing": ("dressing", "towel", "flower", "green room", "robe"),
}


def _spend_row(text: str) -> str:
    low = (text or "").lower()
    for row, words in _SPEND_ROWS.items():
        if any(w in low for w in words):
            return row
    return "Other"


def _hospitality(conn) -> dict:
    """Spend by row against the cap, for 32:2. Hospitality lines only — a
    technical line has no unit cost, so including it would dilute the chart
    with rows that cannot be priced."""
    rows = db.rows(conn.execute(
        "SELECT raw_text, quantity, unit_cost FROM rider_items WHERE category = 'hospitality'"))
    out = {name: {"name": name, "spend": 0.0, "lines": 0}
           for name in ("Catering", "Drinks", "Dressing", "Other")}
    for r in rows:
        bucket = out[_spend_row(r["raw_text"])]
        bucket["spend"] += (r["unit_cost"] or 0) * (r["quantity"] or 0)
        bucket["lines"] += 1
    # data/rules/hospitality.yaml: an artist's own cap overrides default_cap,
    # and most artists have none, so summing the column alone understates it.
    caps = conn.execute(
        """SELECT COALESCE(SUM(COALESCE(hospitality_cap, 1000)), 0) FROM artists
           WHERE id IN (SELECT DISTINCT artist_id FROM rider_items)""").fetchone()[0]
    return {
        "spend_total": round(sum(b["spend"] for b in out.values())),
        "cap_total": round(caps),
        "rows": [{**b, "spend": round(b["spend"])} for b in out.values()],
    }


def _readiness(conn) -> dict:
    """The five-way split behind the arc and legend on 35:2.

    Every artist and vendor falls in exactly ONE bucket, so the five add up to
    the supplier count. Counting by `status` alone double-counts: an artist can
    be `completed` and have no document on file at the same time."""
    count = lambda sql, *a: conn.execute(sql, a).fetchone()[0]  # noqa: E731
    has_doc = ("EXISTS (SELECT 1 FROM documents d "
               "WHERE d.owner_type = 'artist' AND d.owner_id = a.id)")
    open_findings = ("EXISTS (SELECT 1 FROM tickets t JOIN findings f ON f.ticket_id = t.id "
                     "WHERE t.owner_type = 'artist' AND t.owner_id = a.id AND f.status = 'open')")
    return {
        # Paperwork in, nothing outstanding.
        "cleared_rider": count(
            f"SELECT COUNT(*) FROM artists a WHERE {has_doc} AND NOT {open_findings}"),
        "cleared_vendor": count("SELECT COUNT(*) FROM vendors WHERE status = 'completed'"),
        # Paperwork in, something still open — artists and vendors together.
        "in_progress": count(f"SELECT COUNT(*) FROM artists a WHERE {has_doc} AND {open_findings}")
                       + count("SELECT COUNT(*) FROM vendors WHERE status != 'completed'"),
        # Booked onto the run sheet, but nothing has arrived from them.
        "not_started": count(
            f"SELECT COUNT(*) FROM artists a WHERE NOT {has_doc} AND a.set_start IS NOT NULL"),
        # Not even scheduled yet.
        "not_received": count(
            f"SELECT COUNT(*) FROM artists a WHERE NOT {has_doc} AND a.set_start IS NULL"),
    }


@router.get("/artists")
def list_artists() -> list[dict]:
    with db.get_conn() as conn:
        return db.rows(conn.execute(
            """SELECT a.*, s.name AS stage_name,
                      (SELECT t.id FROM tickets t WHERE t.owner_type = 'artist' AND t.owner_id = a.id
                       ORDER BY t.updated_at DESC LIMIT 1) AS latest_ticket_id
               FROM artists a LEFT JOIN stages s ON s.id = a.stage_id
               ORDER BY a.set_start IS NULL, a.set_start, a.name"""
        ))


@router.get("/stages")
def list_stages() -> list[dict]:
    """The stages on their own, so a form can offer them by id. Deriving the list
    from whatever inventory or artists happen to carry a stage silently drops any
    stage nothing is on yet."""
    with db.get_conn() as conn:
        return db.rows(conn.execute("SELECT id, name, location FROM stages ORDER BY id"))


def _inventory(only: int | None = None) -> list[dict]:
    """Inventory with its reservations attached. `only` narrows to one item so a
    write can answer in exactly the shape the list sends."""
    with db.get_conn() as conn:
        items = db.rows(conn.execute(
            f"""SELECT i.*, s.name AS stage_name FROM inventory_items i
                LEFT JOIN stages s ON s.id = i.stage_id
                {"WHERE i.id = ?" if only is not None else ""}
                ORDER BY i.stage_id IS NULL, i.stage_id, i.canonical_name""",
            () if only is None else (only,)
        ))
        allocs = db.rows(conn.execute(
            """SELECT al.*, a.name AS artist_name FROM allocations al JOIN artists a ON a.id = al.artist_id
               WHERE al.status = 'reserved' ORDER BY al.start_ts"""
        ))
    for i in items:
        i["aliases"] = json.loads(i.pop("aliases_json") or "[]")
        i["allocations"] = [
            {k: a[k] for k in ("artist_id", "artist_name", "quantity", "start_ts", "end_ts")}
            for a in allocs if a["inventory_item_id"] == i["id"]
        ]
    return items


@router.get("/inventory")
def list_inventory() -> list[dict]:
    return _inventory()


@router.get("/runsheet")
def runsheet() -> list[dict]:
    return [r.model_dump() for r in build_runsheet()]


# --- adding a row -----------------------------------------------------------------------
# Both tables were read-only, so a row the operator typed had nowhere to go. Every refusal
# below raises HTTPException with a string detail on purpose: FastAPI's own 422 puts a list
# under `detail`, and the frontend's ApiError can only show a string inline. Validating by
# hand off a Body dict is also the style the ticket routes already use.

_NAME_MAX = 80
_CATEGORY_MAX = 40
#: A four-figure total would push the numeral out of its 94px Total track (Figma 228:17),
#: and no single venue owns a thousand of anything.
_QTY_MAX = 999


def _text(payload: dict, field: str, missing: str, limit: int) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(422, missing)
    # Collapsed rather than merely stripped: "DI   box" and "DI box" are the same item,
    # and only one of them can be caught by the duplicate check below.
    text = " ".join(value.split())
    if len(text) > limit:
        raise HTTPException(422, f"Keep that to {limit} characters or fewer.")
    return text


def _stage_id(conn, payload: dict, missing: str | None) -> int | None:
    """`missing` is the message when the field is required; None means a stage-less
    row is legitimate, which for inventory is the shared pool."""
    raw = payload.get("stage_id")
    if raw is None:
        if missing is not None:
            raise HTTPException(422, missing)
        return None
    # bool is an int in Python, and `true` is not a stage.
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise HTTPException(422, "That is not a stage.")
    if conn.execute("SELECT 1 FROM stages WHERE id = ?", (raw,)).fetchone() is None:
        raise HTTPException(422, "That stage is not on file.")
    return raw


def _timestamp(payload: dict, field: str, label: str) -> str:
    """One naive local timestamp, normalised to the seconds-bearing form every other
    row in the schedule is stored in — the whole app compares these as text."""
    raw = payload.get(field)
    if not isinstance(raw, str) or not raw.strip():
        raise HTTPException(422, f"{label} is required.")
    raw = raw.strip()
    try:
        stamp = datetime.fromisoformat(raw)
    except ValueError:
        raise HTTPException(422, f"{label} must read like 2026-12-12T18:00.")
    # fromisoformat takes a bare date and calls it midnight, which is a time nobody
    # typed. Checked after parsing so gibberish gets the format message instead.
    if "T" not in raw:
        raise HTTPException(422, f"{label} needs a time as well as a date.")
    if stamp.tzinfo is not None:
        raise HTTPException(422, f"{label} must not carry a timezone.")
    return stamp.isoformat(timespec="seconds")


@router.post("/inventory", status_code=201)
def add_inventory_item(payload: dict = Body(default_factory=dict),
                       user: str = Depends(current_user)) -> dict:
    """One inventory row, typed by hand, answered in the shape GET /inventory sends.

    Aliases are not asked for and stay empty. They exist so the rider parser can match
    an artist's wording to an item, which happens at ingest; a row typed on this screen
    has no wording to match."""
    name = _text(payload, "canonical_name", "An item name is required.", _NAME_MAX)
    category = _text(payload, "category", "A category is required.", _CATEGORY_MAX)

    quantity = payload.get("quantity_total")
    if quantity is None:
        raise HTTPException(422, "A total is required.")
    if not isinstance(quantity, int) or isinstance(quantity, bool):
        raise HTTPException(422, "The total must be a whole number.")
    if not 1 <= quantity <= _QTY_MAX:
        raise HTTPException(422, f"The total must be between 1 and {_QTY_MAX}.")

    with db.get_conn() as conn:
        stage_id = _stage_id(conn, payload, None)
        # Two rows for one real item would split Reserved and Free between them, so the
        # Equipment table would understate both and a shortage could hide in the gap.
        # `IS` rather than `=` so the shared pool's NULL stage compares equal to itself.
        twin = db.row(conn.execute(
            """SELECT i.canonical_name, s.name AS stage_name FROM inventory_items i
               LEFT JOIN stages s ON s.id = i.stage_id
               WHERE LOWER(i.canonical_name) = LOWER(?) AND i.stage_id IS ?""",
            (name, stage_id)
        ))
        if twin is not None:
            # Named as it is spelled on file, not as it was just typed, so the operator
            # can find the row that already exists.
            raise HTTPException(409, f"{twin['stage_name'] or 'The shared pool'} "
                                     f"already lists a {twin['canonical_name']}.")
        item_id = int(conn.execute(
            """INSERT INTO inventory_items (stage_id, canonical_name, category, quantity_total)
               VALUES (?, ?, ?, ?)""",
            (stage_id, name, category, quantity)
        ).lastrowid)
        audit(conn, None, user, "inventory_item_added",
              {"inventory_item_id": item_id, "canonical_name": name,
               "stage_id": stage_id, "quantity_total": quantity})

    return _inventory(item_id)[0]


@router.post("/runsheet/sets", status_code=201)
def add_runsheet_set(payload: dict = Body(default_factory=dict),
                     user: str = Depends(current_user)) -> dict:
    """A set row for an artist who applied but holds no slot yet.

    Only `artists` is written. The Needs column is the approved technical rider, so
    reserving equipment from here would write an allocation no rider was ever approved
    for, and the Equipment screen would report a shortage nobody asked for."""
    start = _timestamp(payload, "start", "A start time")
    end = _timestamp(payload, "end", "An end time")
    if end <= start:
        raise HTTPException(422, "The set has to end after it starts.")
    # build_runsheet files a row under the day its start falls on, so a set running past
    # midnight would be listed on a day it is not playing.
    if start[:10] != end[:10]:
        raise HTTPException(422, "A set has to start and end on the same day.")

    with db.get_conn() as conn:
        festival = db.row(conn.execute("SELECT start_date, end_date FROM festival LIMIT 1")) or {}
        first, last = festival.get("start_date", ""), festival.get("end_date", "")
        # The day tabs are read off the rows themselves, so a set outside the festival
        # grows a fourth tab on a three-day event.
        if not first <= start[:10] <= last:
            raise HTTPException(422, f"The festival runs {first} to {last}.")

        stage_id = _stage_id(conn, payload, "Pick a stage.")

        artist_id = payload.get("artist_id")
        if not isinstance(artist_id, int) or isinstance(artist_id, bool):
            raise HTTPException(422, "Pick an artist.")
        # Matched on id, never on name: nothing in this schema makes artists.name unique.
        artist = db.row(conn.execute("SELECT * FROM artists WHERE id = ?", (artist_id,)))
        if artist is None:
            raise HTTPException(404, "That artist is not on file.")
        if artist["set_start"] is not None:
            raise HTTPException(409, f"{artist['name']} is already on the run sheet.")

        # Two bands on one stage at one moment is not a conflict to surface later, it is
        # a row that cannot be true, so it is refused rather than written and flagged.
        clash = db.row(conn.execute(
            """SELECT name, set_start, set_end FROM artists
               WHERE stage_id = ? AND set_start IS NOT NULL AND set_start < ? AND ? < set_end
               ORDER BY set_start LIMIT 1""",
            (stage_id, end, start)
        ))
        if clash is not None:
            raise HTTPException(409, f"{clash['name']} already plays {clash['set_start'][11:16]} to "
                                     f"{clash['set_end'][11:16]} on that stage.")

        stage_name = conn.execute("SELECT name FROM stages WHERE id = ?", (stage_id,)).fetchone()[0]
        # `applied` means unscheduled everywhere else in this codebase — _readiness reads
        # it as "not even scheduled yet" — so a booked slot cannot stay applied.
        conn.execute(
            """UPDATE artists SET stage_id = ?, set_start = ?, set_end = ?, status = 'in_progress'
               WHERE id = ?""",
            (stage_id, start, end, artist_id)
        )
        audit(conn, None, user, "set_scheduled",
              {"artist_id": artist_id, "stage_id": stage_id, "start": start, "end": end})

    return RunsheetRow(
        day=_day(start), start=start, end=end, area=stage_name, who=artist["name"],
        kind="set", status="in_progress", contact=artist["manager_email"],
        artist_id=artist_id,
    ).model_dump()


# --- taking a row back off ---------------------------------------------------------------
# The mirror of the two POSTs above, and the reason they are safe to try: a row typed by
# hand is a row that can be typed wrong, and before this the only way back was SQL.
# Both refuse anything an approved rider is standing on, because removing one of those
# would leave a reservation pointing at nothing and quietly change what the Equipment
# screen reports is free.


@router.delete("/inventory/{item_id}")
def remove_inventory_item(item_id: int, user: str = Depends(current_user)) -> dict:
    with db.get_conn() as conn:
        item = db.row(conn.execute("SELECT * FROM inventory_items WHERE id = ?", (item_id,)))
        if item is None:
            raise HTTPException(404, "That item is not on file.")
        # Counted, not just detected: "reserved by 3 sets" tells the operator how much
        # work undoing this would be, which a bare refusal does not.
        held = conn.execute(
            """SELECT COUNT(*) FROM allocations
               WHERE inventory_item_id = ? AND status = 'reserved'""",
            (item_id,)
        ).fetchone()[0]
        if held:
            raise HTTPException(409, f"{item['canonical_name']} is reserved by {held} "
                                     f"{'set' if held == 1 else 'sets'}. Release those first.")
        conn.execute("DELETE FROM inventory_items WHERE id = ?", (item_id,))
        audit(conn, None, user, "inventory_item_removed",
              {"inventory_item_id": item_id, "canonical_name": item["canonical_name"],
               "stage_id": item["stage_id"], "quantity_total": item["quantity_total"]})
    return {"ok": True, "inventory_item_id": item_id}


@router.delete("/runsheet/sets/{artist_id}")
def remove_runsheet_set(artist_id: int, user: str = Depends(current_user)) -> dict:
    """Takes an artist back off the sheet. The artist stays; only the slot goes.

    Deleting the record would take the rider, its findings and its ticket with it, and
    an act whose slot was entered wrongly has not withdrawn from the festival."""
    with db.get_conn() as conn:
        artist = db.row(conn.execute("SELECT * FROM artists WHERE id = ?", (artist_id,)))
        if artist is None:
            raise HTTPException(404, "That artist is not on file.")
        if artist["set_start"] is None:
            raise HTTPException(409, f"{artist['name']} is not on the run sheet.")
        held = conn.execute(
            "SELECT COUNT(*) FROM allocations WHERE artist_id = ? AND status = 'reserved'",
            (artist_id,)
        ).fetchone()[0]
        if held:
            raise HTTPException(409, f"{artist['name']} has equipment reserved from an "
                                     f"approved rider. Release it before moving the set.")
        # Back to `applied`, which is what the rest of the codebase reads as unscheduled —
        # _readiness buckets on it, so leaving `in_progress` here would show an act as
        # part-way through with nothing to be part-way through.
        conn.execute(
            """UPDATE artists SET stage_id = NULL, set_start = NULL, set_end = NULL,
                                  status = 'applied' WHERE id = ?""",
            (artist_id,)
        )
        audit(conn, None, user, "set_unscheduled",
              {"artist_id": artist_id, "stage_id": artist["stage_id"],
               "start": artist["set_start"], "end": artist["set_end"]})
    return {"ok": True, "artist_id": artist_id}


@router.get("/export/runsheet.xlsx")
def export_runsheet() -> Response:
    return Response(
        runsheet_xlsx(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="riverside_runsheet.xlsx"'},
    )


def _document(doc_id: int) -> dict:
    with db.get_conn() as conn:
        doc = db.row(conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)))
    if doc is None:
        raise HTTPException(404, "Document not found")
    return doc


@router.get("/documents/{doc_id}/file", response_model=None)
def document_file(doc_id: int):
    doc = _document(doc_id)
    path = riders.resolve_path(doc["path"])
    if path is None:
        # Pasted riders have no file: serve the text.
        return PlainTextResponse(doc["extracted_text"] or "")
    return FileResponse(path, filename=doc["filename"],
                        content_disposition_type="inline")


@router.get("/documents/{doc_id}/highlights")
def document_highlights(doc_id: int) -> list[dict]:
    """One entry per box. type is pdf (points), image (pixels) or text (character offsets to underline)."""
    _document(doc_id)
    with db.get_conn() as conn:
        # `low_confidence` is excluded on purpose. Yellow means exactly one
        # thing on this product — "Low capacity", as the legend says — and a
        # line the parser could not place is not a capacity problem. Drawing it
        # in the same colour tells the operator the wrong thing, and there is
        # no third colour for it to wear. The finding still exists on the
        # ticket; it just is not painted on the page.
        findings = db.rows(conn.execute(
            """SELECT id, severity, status, bbox_json FROM findings
               WHERE doc_id = ? AND status != 'ignored' AND kind != 'low_confidence'""",
            (doc_id,)))
    out = []
    for f in findings:
        box = json.loads(f["bbox_json"]) if f["bbox_json"] else {}
        base = {"type": box.get("kind", "pdf"), "page": box.get("page", 1), "finding_id": f["id"],
                "severity": f["severity"], "status": f["status"]}
        if base["type"] == "text":
            out.append({**base, "start": box["start"], "end": box["end"]})
        for rect in box.get("rects", []):
            out.append({**base, "rect": rect, "page_size": box["page_size"]})
    return out


@router.post("/uploads")
async def upload_files(files: list[UploadFile] = File(...), user: str = Depends(current_user)) -> list[dict]:
    """Equipment lists become inventory rows; anything else is kept as Bumpin's memory."""
    out = []
    for f in files:
        data = await f.read()
        try:
            out.append(uploads.ingest(f.filename or "upload", data))
        except Exception as e:  # one unreadable file must not lose the others
            out.append({"filename": f.filename, "stored_as": "failed", "summary": f"Could not read this file ({type(e).__name__})."})
    return out


@router.get("/memory")
def memory() -> list[dict]:
    return uploads.list_memory()
