"""Files Ravi uploads on the Upload screen.

An equipment list becomes rows in `inventory_items`, and the rider checks are re-run
so new or changed stock shows up as conflicts. Anything else (the festival brief,
hospitality policy, vendor rules) is kept as Bumpin's memory: its text is given to
the AI when it explains a finding, reads a change email or words a reply, and the
file is listed in that email's context_used.

Deciding what a file is goes code first: a table with item and quantity columns is
an equipment list. Only files code cannot place are put to the AI.
"""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from backend.app import db
from backend.app.artists import ai
from backend.app.shared import llm

UPLOAD_DIR = db.DATA_DIR / "uploads"
TEXT_EXT = {".csv", ".tsv", ".txt", ".md", ".json"}
SHEET_EXT = {".xlsx", ".xlsm"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}
MEMORY_PROMPT_CHARS = 4000
MEMORY_FILE_CHARS = 1500

Kind = Literal["equipment", "festival_brief", "policy", "rider", "vendor_document", "other"]

MEMORY_SQL = """CREATE TABLE IF NOT EXISTS memory (
    id INTEGER PRIMARY KEY,
    filename TEXT NOT NULL,
    path TEXT NOT NULL,
    kind TEXT NOT NULL,
    text TEXT,
    summary TEXT,
    uploaded_at TEXT NOT NULL
)"""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def ensure_memory_table(conn) -> None:
    # demo-reset restores a baseline file that may predate this table.
    conn.execute(MEMORY_SQL)


# --- reading files -------------------------------------------------------------------------

def save_upload(filename: str, data: bytes) -> Path:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename).name) or "upload"
    path = UPLOAD_DIR / f"{datetime.now():%Y%m%d%H%M%S%f}_{safe}"
    path.write_bytes(data)
    return path


def table_rows(path: Path) -> list[dict[str, str]]:
    """Rows of a CSV, TSV or spreadsheet, keyed by the header row. [] for anything else."""
    suffix = path.suffix.lower()
    if suffix in (".csv", ".tsv"):
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        return list(csv.DictReader(io.StringIO(text), delimiter="\t" if suffix == ".tsv" else ","))
    if suffix in SHEET_EXT:
        from openpyxl import load_workbook

        ws = load_workbook(path, read_only=True, data_only=True).active
        values = [[("" if v is None else str(v)) for v in r] for r in ws.iter_rows(values_only=True)]
        if not values:
            return []
        head = [h.strip() for h in values[0]]
        return [dict(zip(head, r)) for r in values[1:] if any(c.strip() for c in r)]
    return []


def file_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in TEXT_EXT:
        return path.read_text(encoding="utf-8-sig", errors="replace")
    if suffix in SHEET_EXT:
        rows = table_rows(path)
        if not rows:
            return ""
        out = io.StringIO()
        w = csv.DictWriter(out, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
        return out.getvalue()
    if suffix == ".pdf":
        return "\n".join(p.text for p in llm.extract_text(str(path)))
    if suffix in IMAGE_EXT:
        from backend.app.artists.riders import _deglue, ocr_image

        return "\n".join(_deglue(l["text"]) for l in ocr_image(path)["lines"])
    return ""


# --- what is this file ----------------------------------------------------------------------

_COLS = {
    "stage": ("stage", "location", "venue", "area", "zone"),
    "item": ("item", "equipment", "name", "description", "gear"),
    "category": ("category", "type", "department"),
    "quantity": ("quantity", "qty", "count", "total", "units", "number"),
    "aliases": ("also known as", "aliases", "alias", "aka", "other names"),
}


def _column(headers: list[str], role: str) -> str | None:
    for h in headers:
        low = h.strip().lower()
        if any(low == k or low.startswith(k) for k in _COLS[role]):
            return h
    return None


def is_equipment_table(headers: list[str]) -> bool:
    """Item and quantity columns, and no price column (a priced list is a policy)."""
    has_price = any(re.search(r"cost|price|aud|\$", h, re.I) for h in headers)
    return bool(_column(headers, "item") and _column(headers, "quantity")) and not has_price


def kind_from_name(filename: str) -> Kind:
    n = filename.lower()
    if re.search(r"equipment|manifest|inventory|backline|stock", n):
        return "equipment"
    if re.search(r"brief|overview|festival|event", n):
        return "festival_brief"
    if re.search(r"polic|rule|requirement|hospitality|terms|guideline|budget", n):
        return "policy"
    if re.search(r"rider", n):
        return "rider"
    if re.search(r"certificate|permit|insurance|licen", n):
        return "vendor_document"
    return "other"


class _Classified(BaseModel):
    kind: Kind
    summary: str


_CLASSIFY_PROMPT = """A festival production manager uploaded a file to the festival's operations tool.
Decide what it is:
- "equipment": a list of equipment the venue or stages own, with quantities
- "festival_brief": facts about the festival (dates, stages, people, times)
- "policy": rules, budgets, caps, prices or requirements the team works to
- "rider": an artist's list of technical or hospitality needs
- "vendor_document": a vendor's certificate, permit or insurance
- "other": anything else
Also write a one sentence summary of what the file says, with no em dashes or en dashes.

File name: {name}
Content (may be cut short):
{text}

Respond with JSON: {{"kind": "...", "summary": "..."}}"""


def classify(filename: str, text: str, headers: list[str]) -> tuple[Kind, str, str]:
    """(kind, summary, how) where how says whether code or the AI decided."""
    if headers and is_equipment_table(headers):
        return "equipment", f"Equipment list with columns {', '.join(h for h in headers if h)}.", "code"
    named = kind_from_name(filename)
    if ai.llm_enabled() and text.strip():
        try:
            out = llm.complete_json(_CLASSIFY_PROMPT.format(name=filename, text=text[:3000]), _Classified)
            # A clear file name wins over the AI, which can read "vendor requirements" as a vendor's document.
            return (named if named != "other" else out.kind), ai.clean_text(out.summary), "ai"
        except Exception:
            pass
    kind = named
    first = next((l.strip() for l in text.splitlines() if l.strip()), "")
    return kind, (f"Starts: {first[:120]}" if first else "No readable text."), "filename"


# --- equipment -------------------------------------------------------------------------------

class EquipmentRow(BaseModel):
    stage: str = ""
    item: str
    category: str = "other"
    quantity: int
    aliases: list[str] = []


class _EquipmentList(BaseModel):
    rows: list[EquipmentRow]


_EQUIPMENT_PROMPT = """This document lists equipment a festival owns. Return every item as a row:
stage (the stage it belongs to, or "" for a shared pool), item, category (one word), quantity (integer),
aliases (other names for it, may be empty). Copy names exactly as written.

{text}

Respond with JSON: {{"rows": [...]}}"""

_QTY_LINE = re.compile(r"^\s*[-*•]?\s*(\d+)\s*[xX×]\s*(.+?)\s*$")


def equipment_rows(path: Path, text: str) -> list[EquipmentRow]:
    rows = table_rows(path)
    if rows and is_equipment_table(list(rows[0].keys())):
        head = list(rows[0].keys())
        col = {role: _column(head, role) for role in _COLS}
        out = []
        for r in rows:
            item = (r.get(col["item"]) or "").strip()
            qty = re.sub(r"[^\d]", "", r.get(col["quantity"]) or "")
            if not item or not qty:
                continue
            aliases = re.split(r"[;|]", r.get(col["aliases"]) or "") if col["aliases"] else []
            out.append(EquipmentRow(
                stage=(r.get(col["stage"]) or "").strip() if col["stage"] else "",
                item=item,
                category=((r.get(col["category"]) or "").strip() if col["category"] else "") or "other",
                quantity=int(qty),
                aliases=[a.strip() for a in aliases if a.strip()],
            ))
        return out
    if ai.llm_enabled() and text.strip():
        try:
            return llm.complete_json(_EQUIPMENT_PROMPT.format(text=text[:6000]), _EquipmentList).rows
        except Exception:
            pass
    # Without the AI: "2x Shure SM58" lines, filed under the last stage name seen as a heading.
    with db.get_conn() as conn:
        stages = [r["name"] for r in db.rows(conn.execute("SELECT name FROM stages"))]
    out, stage = [], ""
    for line in text.splitlines():
        m = _QTY_LINE.match(line)
        if m:
            out.append(EquipmentRow(stage=stage, item=m.group(2), quantity=int(m.group(1))))
        else:
            stage = next((s for s in stages if s.lower() in line.lower()), stage)
    return out


def apply_equipment(rows: list[EquipmentRow]) -> dict:
    """Add new items and update changed ones. Never deletes: an upload adds to the record."""
    added = updated = unchanged = 0
    unknown: set[str] = set()
    with db.get_conn() as conn:
        stages = {r["name"].lower(): r["id"] for r in db.rows(conn.execute("SELECT id, name FROM stages"))}
        for r in rows:
            key = r.stage.strip().lower()
            stage_id = stages.get(key)
            if stage_id is None and key not in ("", "shared", "shared pool", "pool"):
                unknown.add(r.stage)
            existing = db.row(conn.execute(
                "SELECT * FROM inventory_items WHERE stage_id IS ? AND lower(canonical_name) = lower(?)",
                (stage_id, r.item.strip())))
            if existing is None:
                conn.execute(
                    """INSERT INTO inventory_items (stage_id, canonical_name, category, quantity_total, aliases_json)
                       VALUES (?, ?, ?, ?, ?)""",
                    (stage_id, r.item.strip(), r.category, r.quantity, json.dumps(r.aliases)))
                added += 1
                continue
            old_aliases = json.loads(existing["aliases_json"] or "[]")
            aliases = old_aliases + [a for a in r.aliases if a.lower() not in {x.lower() for x in old_aliases}]
            if existing["quantity_total"] == r.quantity and aliases == old_aliases:
                unchanged += 1
                continue
            conn.execute("UPDATE inventory_items SET quantity_total = ?, aliases_json = ? WHERE id = ?",
                         (r.quantity, json.dumps(aliases), existing["id"]))
            updated += 1
    return {"added": added, "updated": updated, "unchanged": unchanged, "unknown_stages": sorted(unknown)}


def recheck_artist(artist_id: int) -> int | None:
    """Re-match an artist's rider lines to the equipment on file and re-run the checks.

    The rider is not read again: its lines were parsed when it arrived and an equipment
    upload does not change them. Matching here is by alias only, so the result is the
    same every time and needs no network call. A finding that comes back with the same
    kind and quote keeps the Resolve or Ignore decision it already had."""
    from backend.app.artists import checks
    from backend.app.artists.models import RiderItem
    from backend.app.artists.riders import match_items
    from backend.app.artists.tickets import SEVERITY_RANK, _summary, insert_finding

    with db.get_conn() as conn:
        rows = db.rows(conn.execute("SELECT * FROM rider_items WHERE artist_id = ? ORDER BY id", (artist_id,)))
        ticket = db.row(conn.execute(
            "SELECT * FROM tickets WHERE type = 'rider_needs' AND owner_type = 'artist' AND owner_id = ?",
            (artist_id,)))
    if not rows or ticket is None:
        return None
    items = [RiderItem(id=r["id"], artist_id=artist_id, doc_id=r["doc_id"], name=r["raw_text"] or r["quote"] or "",
                       raw_text=r["raw_text"] or "", quote=r["quote"] or "", page=r["page"] or 1,
                       category=r["category"], quantity=r["quantity"]) for r in rows]
    match_items(items, use_llm=False)
    with db.get_conn() as conn:
        for it in items:
            conn.execute("UPDATE rider_items SET inventory_item_id = ?, unit_cost = ?, match_confidence = ? WHERE id = ?",
                         (it.inventory_item_id, it.unit_cost, it.match_confidence, it.id))

    found = checks.run_all(artist_id)
    kinds = ("shortage", "double_booking", "over_budget", "low_confidence")  # what the checks write
    with db.get_conn() as conn:
        old = {(f["kind"], f["quote"]): f for f in db.rows(conn.execute(
            f"SELECT * FROM findings WHERE ticket_id = ? AND kind IN ({','.join('?' * len(kinds))})",
            (ticket["id"], *kinds)))}
        before = {k: f["status"] for k, f in old.items() if f["status"] != "open"}
        # Other findings (the yellow caution notes) are not the checks' to rewrite.
        conn.execute(f"DELETE FROM findings WHERE ticket_id = ? AND kind IN ({','.join('?' * len(kinds))})",
                     (ticket["id"], *kinds))
        for f in found:
            fid = insert_finding(conn, ticket["id"], f)
            prev = old.get((f.kind, f.quote))
            if prev is None:
                continue
            if prev["status"] != "open":
                conn.execute("UPDATE findings SET status = ? WHERE id = ?", (prev["status"], fid))
            # Keep a box that could not be found again, such as one placed by hand on a handwritten page.
            new_box = json.loads(conn.execute("SELECT bbox_json FROM findings WHERE id = ?", (fid,)).fetchone()[0] or "{}")
            old_box = json.loads(prev["bbox_json"] or "{}")
            if not new_box.get("rects") and old_box.get("rects") and prev["doc_id"] == f.doc_id:
                conn.execute("UPDATE findings SET bbox_json = ?, page = ? WHERE id = ?",
                             (json.dumps({**old_box, "facts": new_box.get("facts", old_box.get("facts", {}))}),
                              prev["page"], fid))
        still_open = [f for f in found if before.get((f.kind, f.quote), "open") == "open"]
        severity = max((f.severity for f in found), key=SEVERITY_RANK.get, default="info")
        if ticket["status"] in ("approved", "rejected"):
            conn.execute("UPDATE tickets SET severity = ?, updated_at = ? WHERE id = ?",
                         (severity, _now(), ticket["id"]))
        else:
            conn.execute("UPDATE tickets SET status = ?, severity = ?, summary = ?, updated_at = ? WHERE id = ?",
                         ("needs_review" if still_open else "in_progress" if found else "open", severity,
                          _summary(conn, artist_id, found, len(items)), _now(), ticket["id"]))
    return ticket["id"]


def rerun_rider_checks() -> int:
    """Re-check every artist with a rider against the equipment just uploaded.

    Twice: the double-booking check reads other artists' matches, so the first pass
    can only see a shared-pool clash from one side."""
    with db.get_conn() as conn:
        artists = [r["artist_id"] for r in db.rows(conn.execute("SELECT DISTINCT artist_id FROM rider_items"))]
    for _ in range(2):
        for artist_id in artists:
            recheck_artist(artist_id)
    return len(artists)


# --- memory ------------------------------------------------------------------------------------

def remember(filename: str, path: Path, kind: str, text: str, summary: str) -> int:
    with db.get_conn() as conn:
        ensure_memory_table(conn)
        cur = conn.execute(
            "INSERT INTO memory (filename, path, kind, text, summary, uploaded_at) VALUES (?, ?, ?, ?, ?, ?)",
            (filename, str(path.relative_to(db.ROOT)), kind, text, summary, _now()))
        return int(cur.lastrowid)


def list_memory() -> list[dict]:
    with db.get_conn() as conn:
        ensure_memory_table(conn)
        rows = db.rows(conn.execute(
            "SELECT id, filename, kind, summary, uploaded_at, length(text) AS chars FROM memory ORDER BY id DESC"))
    return rows


def memory_context() -> tuple[str, list[str]]:
    """Uploaded notes for an AI prompt, newest first, within a size budget, and their file names."""
    with db.get_conn() as conn:
        ensure_memory_table(conn)
        rows = db.rows(conn.execute("SELECT filename, kind, text FROM memory ORDER BY id DESC"))
    parts, names, used = [], [], 0
    for r in rows:
        chunk = f"## {r['filename']} ({r['kind'].replace('_', ' ')})\n{(r['text'] or '')[:MEMORY_FILE_CHARS]}"
        if used + len(chunk) > MEMORY_PROMPT_CHARS:
            break
        parts.append(chunk)
        names.append(r["filename"])
        used += len(chunk)
    return "\n\n".join(parts), names


# --- one upload ------------------------------------------------------------------------------

def ingest(filename: str, data: bytes) -> dict:
    path = save_upload(filename, data)
    text = file_text(path)
    rows = table_rows(path)
    kind, summary, how = classify(filename, text, list(rows[0].keys()) if rows else [])
    result = {"filename": filename, "kind": kind, "summary": summary, "decided_by": how}

    if kind == "equipment":
        items = equipment_rows(path, text)
        if items:
            counts = apply_equipment(items)
            changed = counts["added"] + counts["updated"]
            result.update(stored_as="equipment", equipment=counts,
                          riders_rechecked=rerun_rider_checks() if changed else 0)
            return result
        result["summary"] = "Looked like an equipment list, but no rows with a quantity could be read."
    result.update(stored_as="memory", memory_id=remember(filename, path, kind, text, summary))
    return result
