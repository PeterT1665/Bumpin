"""Rider extraction, inventory matching and PDF highlight boxes."""

from __future__ import annotations

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


def _norm(text: str) -> str:
    return " " + re.sub(r"[^a-z0-9]+", " ", text.lower()).strip() + " "


def resolve_path(path: str | None) -> Path | None:
    if not path:
        return None
    p = Path(path)
    if not p.is_absolute():
        p = db.ROOT / p
    return p if p.exists() else None


def document_pages(doc: dict) -> list[tuple[int, str]]:
    """Text per page from the file, or from extracted_text for pasted riders."""
    p = resolve_path(doc.get("path"))
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
        if raw.quote not in page_text.get(page, ""):
            found = next((p for p, t in pages if raw.quote in t), None)
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


def match_items(items: list[RiderItem], stage_id: int | None = None) -> list[RiderItem]:
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
        item_id, conf = ai.llm_match(item.name, candidates)
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

def locate(doc_id: int | None, page: int | None, quote: str | None) -> dict | None:
    """PDF rectangles for a quote, in points with origin top-left."""
    if not doc_id or not quote:
        return None
    with db.get_conn() as conn:
        doc = db.row(conn.execute("SELECT path FROM documents WHERE id = ?", (doc_id,)))
    p = resolve_path(doc and doc["path"])
    if p is None or p.suffix.lower() != ".pdf":
        return None
    with fitz.open(str(p)) as pdf:
        pages = [page - 1] if page and 0 < page <= len(pdf) else range(len(pdf))
        for i in pages:
            rects = pdf[i].search_for(quote)
            if rects:
                pg = pdf[i]
                return {
                    "page": i + 1,
                    "page_size": [round(pg.rect.width, 1), round(pg.rect.height, 1)],
                    "rects": [[round(r.x0, 1), round(r.y0, 1), round(r.x1, 1), round(r.y1, 1)] for r in rects],
                }
    return None
