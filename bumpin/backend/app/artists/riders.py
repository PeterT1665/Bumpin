"""Rider extraction, inventory matching and PDF highlight boxes."""

from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path

import fitz

from backend.app import db
from backend.app.artists import ai
from backend.app.artists.models import RiderItem
from backend.app.shared.llm import extract_text
from backend.app.shared.rules import load_rules

ALIAS_CONFIDENCE = 0.95
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}
MIN_OCR_CONFIDENCE = 0.4


def _norm(text: str) -> str:
    return " " + re.sub(r"[^a-z0-9]+", " ", text.lower()).strip() + " "


def resolve_path(path: str | None) -> Path | None:
    if not path:
        return None
    p = Path(path)
    if not p.is_absolute():
        p = db.ROOT / p
    return p if p.exists() else None


def _squash(text: str) -> str:
    """Lowercase letters and digits only, so spacing and OCR glue never break a match."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _deglue(line: str) -> str:
    """Put back spaces OCR drops: '3xPioneerCDJ-3000' becomes '3x Pioneer CDJ-3000'."""
    line = re.sub(r"^(\d+)\s*[xX\u00d7]\s*", r"\1x ", line.strip())
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", line)


# --- photos: OCR gives text and a box per line ---------------------------------------

_engine = None


def ocr_image(path: Path) -> dict:
    """{"size": [w, h], "lines": [{"text", "rect": [x0, y0, x1, y1]}]} in image pixels.

    Cached on disk by file hash, so the demo replays without running OCR again.
    """
    key = hashlib.sha256(path.read_bytes()).hexdigest()[:24]
    cache = db.DATA_DIR / "llm_cache" / f"ocr_{key}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))

    global _engine
    from PIL import Image
    from rapidocr_onnxruntime import RapidOCR

    _engine = _engine or RapidOCR()
    result, _ = _engine(str(path))
    with Image.open(path) as im:
        size = list(im.size)
    lines = []
    for box, text, conf in result or []:
        if float(conf) < MIN_OCR_CONFIDENCE:
            continue
        xs, ys = [pt[0] for pt in box], [pt[1] for pt in box]
        lines.append({"text": text, "rect": [round(min(xs), 1), round(min(ys), 1),
                                              round(max(xs), 1), round(max(ys), 1)]})
    data = {"size": size, "lines": lines}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data), encoding="utf-8")
    return data


def document_pages(doc: dict) -> list[tuple[int, str]]:
    """Text per page: PDF text layer, OCR for photos, or extracted_text for emails."""
    p = resolve_path(doc.get("path"))
    if p is not None and p.suffix.lower() in IMAGE_EXT:
        return [(1, "\n".join(_deglue(l["text"]) for l in ocr_image(p)["lines"]))]
    if p is not None:
        return [(pt.page, pt.text) for pt in extract_text(str(p))]
    return [(1, doc.get("extracted_text") or "")]


# --- extraction --------------------------------------------------------------

def extract_rider(doc_id: int) -> list[RiderItem]:
    """Every requested item with its exact quote and page."""
    with db.get_conn() as conn:
        doc = db.row(conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)))
    if doc is None:
        raise KeyError(f"document {doc_id} not found")

    pages = document_pages(doc)
    if not doc.get("extracted_text"):
        with db.get_conn() as conn:
            conn.execute("UPDATE documents SET extracted_text = ? WHERE id = ?",
                         ("\n\n".join(t for _, t in pages), doc_id))

    page_text = dict(pages)
    items = []
    for raw in ai.extract_items(pages):
        page = raw.page if raw.page in page_text else 1
        # Keep only quotes we can find, so every claim is traceable.
        if _squash(raw.quote) not in _squash(page_text.get(page, "")):
            found = next((p for p, t in pages if _squash(raw.quote) in _squash(t)), None)
            if found is None:
                continue
            page = found
        items.append(RiderItem(
            artist_id=doc["owner_id"] if doc["owner_type"] == "artist" else None,
            doc_id=doc_id,
            name=raw.name,
            raw_text=raw.quote,
            quote=raw.quote,
            page=page,
            category=raw.category,
            quantity=max(raw.quantity, 1),
        ))
    return items


# --- matching ------------------------------------------------------------------

@lru_cache(maxsize=1)
def _hospitality_catalog() -> list[tuple[str, str, float]]:
    """(normalised alias, label, unit_cost), longest alias first."""
    rules = load_rules("hospitality")
    out = []
    for key, item in (rules.get("items") or {}).items():
        for alias in [item["label"], *item.get("aliases", [])]:
            out.append((_norm(alias), item["label"], float(item["unit_cost"])))
    return sorted(out, key=lambda a: len(a[0]), reverse=True)


def _stage_candidates(stage_id: int | None) -> list[dict]:
    with db.get_conn() as conn:
        return db.rows(conn.execute(
            "SELECT * FROM inventory_items WHERE stage_id IS ? OR stage_id IS NULL",
            (stage_id,),
        ))


def _alias_match(name: str, candidates: list[dict]) -> dict | None:
    text = _norm(name)
    best, best_len = None, 0
    for c in candidates:
        for alias in [c["canonical_name"], *json.loads(c["aliases_json"] or "[]")]:
            a = _norm(alias)
            if a in text and len(a) > best_len:
                best, best_len = c, len(a)
    return best


def match_items(items: list[RiderItem], stage_id: int | None = None, *, use_llm: bool = True) -> list[RiderItem]:
    """Aliases first, LLM fallback. Sets match_confidence on every item."""
    if stage_id is None and items and items[0].artist_id:
        with db.get_conn() as conn:
            a = db.row(conn.execute("SELECT stage_id FROM artists WHERE id = ?", (items[0].artist_id,)))
            stage_id = a["stage_id"] if a else None
    candidates = _stage_candidates(stage_id)

    for item in items:
        if item.category == "hospitality":
            text = _norm(item.name)
            hit = next(((label, cost) for alias, label, cost in _hospitality_catalog() if alias in text), None)
            if hit:
                item.match_label, item.unit_cost, item.match_confidence = hit[0], hit[1], ALIAS_CONFIDENCE
            continue

        hit = _alias_match(item.name, candidates)
        if hit:
            item.inventory_item_id = hit["id"]
            item.match_label = hit["canonical_name"]
            item.match_confidence = ALIAS_CONFIDENCE
            continue
        item_id, conf = ai.llm_match(item.name, candidates) if use_llm else (None, 0.0)
        if item_id:
            item.inventory_item_id = item_id
            item.match_label = next(c["canonical_name"] for c in candidates if c["id"] == item_id)
            item.match_confidence = conf
    return items


def save_items(artist_id: int, items: list[RiderItem]) -> list[RiderItem]:
    """A new rider replaces the artist's previous rider items."""
    with db.get_conn() as conn:
        conn.execute("DELETE FROM rider_items WHERE artist_id = ?", (artist_id,))
        for item in items:
            cur = conn.execute(
                """INSERT INTO rider_items (artist_id, doc_id, raw_text, quote, page, category,
                       inventory_item_id, quantity, unit_cost, match_confidence)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (artist_id, item.doc_id, item.raw_text, item.quote, item.page, item.category,
                 item.inventory_item_id, item.quantity, item.unit_cost, item.match_confidence),
            )
            item.id = int(cur.lastrowid)
            item.artist_id = artist_id
    return items


# --- highlights ------------------------------------------------------------------

def _find_span(text: str, quote: str) -> tuple[int, int] | None:
    """Character span of the quote in plain text, ignoring differences in whitespace."""
    words = quote.split()
    if not words:
        return None
    m = re.search(r"\s+".join(re.escape(w) for w in words), text, re.I)
    return (m.start(), m.end()) if m else None


def _locate_image(path: Path, quote: str) -> dict | None:
    data = ocr_image(path)
    lines, target = data["lines"], _squash(quote)
    if not target:
        return None
    for window in (1, 2, 3):
        for i in range(len(lines) - window + 1):
            group = lines[i:i + window]
            joined = "".join(_squash(l["text"]) for l in group)
            at = joined.find(target)
            if at < 0:
                continue
            rects = [list(l["rect"]) for l in group]
            if window == 1 and len(joined) > len(target):
                # The quote is part of a longer line: narrow the box in proportion.
                x0, y0, x1, y1 = rects[0]
                w = x1 - x0
                rects = [[round(x0 + w * at / len(joined), 1), y0,
                          round(x0 + w * (at + len(target)) / len(joined), 1), y1]]
            return {"kind": "image", "page": 1, "page_size": data["size"], "rects": rects}
    return None


def locate(doc_id: int | None, page: int | None, quote: str | None) -> dict | None:
    """Where a quote sits in its document.

    PDF: rectangles in points. Photo: rectangles in image pixels, found by OCR.
    Email text: character offsets to underline. Origin top-left, page_size is the scale.
    """
    if not doc_id or not quote:
        return None
    with db.get_conn() as conn:
        doc = db.row(conn.execute("SELECT path, extracted_text FROM documents WHERE id = ?", (doc_id,)))
    if doc is None:
        return None
    p = resolve_path(doc["path"])
    if p is None:
        span = _find_span(doc["extracted_text"] or "", quote)
        return {"kind": "text", "page": 1, "start": span[0], "end": span[1]} if span else None
    if p.suffix.lower() in IMAGE_EXT:
        return _locate_image(p, quote)
    if p.suffix.lower() != ".pdf":
        return None
    with fitz.open(str(p)) as pdf:
        pages = [page - 1] if page and 0 < page <= len(pdf) else range(len(pdf))
        for i in pages:
            rects = pdf[i].search_for(quote)
            if rects:
                pg = pdf[i]
                return {
                    "kind": "pdf",
                    "page": i + 1,
                    "page_size": [round(pg.rect.width, 1), round(pg.rect.height, 1)],
                    "rects": [[round(r.x0, 1), round(r.y0, 1), round(r.x1, 1), round(r.y1, 1)] for r in rects],
                }
    return None
