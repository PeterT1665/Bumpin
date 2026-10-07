"""LLM calls for the artist side. Each has a deterministic fallback so the
app runs with the fake provider (no API key) and survives bad LLM output.

The LLM reads and drafts. It never decides shortages, overlaps or totals.
"""

from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel

from backend.app.shared import llm
from backend.app.shared.rules import load_rules


def llm_enabled() -> bool:
    return getattr(llm, "_PROVIDER", "fake") != "fake"


def clean_text(text: str) -> str:
    """User-facing text must not contain em or en dashes."""
    return text.replace(" \u2014 ", ", ").replace("\u2014", ", ").replace("\u2013", " to ")


# --- rider extraction ------------------------------------------------------

class _ExtractedItem(BaseModel):
    name: str
    quantity: int
    category: Literal["technical", "hospitality"]
    quote: str
    page: int


class _Extraction(BaseModel):
    items: list[_ExtractedItem]


_EXTRACT_PROMPT = """You read artist riders for a festival. List every requested item.

For each item return:
- name: the item, without the quantity
- quantity: an integer (1 if not stated)
- category: "technical" for stage, audio, DJ, instrument or lighting gear; "hospitality" for food, drink, rooms and comfort items
- quote: the EXACT text of the line as it appears in the document, copied character for character
- page: the page number the line is on

Ignore notes that do not request an item. Respond with JSON: {{"items": [...]}}

Document:
{pages}"""

_ITEM_LINE = re.compile(r"^\s*[-*•]?\s*(\d+)\s*[xX×]\s+(.+?)\s*$")
_HOSPO = re.compile(r"\b(hospitality|hospo|catering|green room)\b", re.I)
_TECH = re.compile(r"\b(technical|tech|backline|equipment|stage)\b", re.I)


def extract_items(pages: list[tuple[int, str]]) -> list[_ExtractedItem]:
    if llm_enabled():
        try:
            joined = "\n\n".join(f"--- page {p} ---\n{t}" for p, t in pages)
            result = llm.complete_json(_EXTRACT_PROMPT.format(pages=joined), _Extraction)
            if result.items:
                return result.items
        except Exception:
            pass
    return heuristic_extract(pages)


def heuristic_extract(pages: list[tuple[int, str]]) -> list[_ExtractedItem]:
    """Reads 'Nx Item' lines, using section headings for the category."""
    items: list[_ExtractedItem] = []
    category: Literal["technical", "hospitality"] = "technical"
    for page, text in pages:
        for line in text.splitlines():
            m = _ITEM_LINE.match(line)
            if not m:
                if _HOSPO.search(line) and len(line) < 40:
                    category = "hospitality"
                elif _TECH.search(line) and len(line) < 40:
                    category = "technical"
                continue
            quote = line.strip().lstrip("-*• ").strip()
            items.append(_ExtractedItem(
                name=m.group(2).strip(),
                quantity=int(m.group(1)),
                category=category,
                quote=quote,
                page=page,
            ))
    return items


# --- inventory matching fallback --------------------------------------------

class _Match(BaseModel):
    inventory_item_id: int | None
    confidence: float


_MATCH_PROMPT = """A festival rider asks for: "{name}".
Which of these stage inventory items is the same thing? Return its id, or null if none is the same model.
Different models (for example CDJ-2000 and CDJ-3000) are NOT the same.
{candidates}
Respond with JSON: {{"inventory_item_id": <id or null>, "confidence": <0 to 1>}}"""


def llm_match(name: str, candidates: list[dict]) -> tuple[int | None, float]:
    if not llm_enabled() or not candidates:
        return None, 0.0
    lines = "\n".join(f"- id {c['id']}: {c['canonical_name']}" for c in candidates)
    try:
        m = llm.complete_json(_MATCH_PROMPT.format(name=name, candidates=lines), _Match)
    except Exception:
        return None, 0.0
    valid = {c["id"] for c in candidates}
    if m.inventory_item_id not in valid:
        return None, 0.0
    # Cap below the alias-match confidence so LLM matches stay reviewable.
    return m.inventory_item_id, min(m.confidence, 0.8)


# --- finding explanations ---------------------------------------------------

class _Explanation(BaseModel):
    message: str
    suggestion: str


_EXPLAIN_PROMPT = """You help a festival production team. Rewrite this check result for a busy production manager.
Keep every number and name exactly as given. Do not invent facts. Two short sentences at most each.
Do not use em dashes or en dashes.

Check: {kind}
Facts: {facts}
Draft message: {message}
Draft suggestion: {suggestion}
Team guidance for this kind of problem: {guidance}

Respond with JSON: {{"message": "...", "suggestion": "..."}}"""


def explain(kind: str, facts: dict, message: str, suggestion: str) -> tuple[str, str]:
    """AI wording on top of a code-computed finding. Falls back to the template."""
    if llm_enabled():
        try:
            guidance = (load_rules("actions") or {}).get(kind, {}).get("action", "")
            out = llm.complete_json(
                _EXPLAIN_PROMPT.format(kind=kind, facts=json.dumps(facts), message=message,
                                       suggestion=suggestion, guidance=guidance),
                _Explanation,
            )
            return clean_text(out.message), clean_text(out.suggestion)
        except Exception:
            pass
    return clean_text(message), clean_text(suggestion)


# --- schedule change parsing -------------------------------------------------

class Change(BaseModel):
    kind: Literal["cancellation", "delay", "time_change", "other"]
    reason: str
    earliest_start: str | None = None  # "HH:MM" if the email says when they can play
    quote: str | None = None


_CHANGE_PROMPT = """An artist's team emailed a festival about their set. Summarise the change.
- kind: "cancellation" (travel cancelled, cannot make the slot), "delay" (running late), "time_change" (asks for a different time), or "other"
- reason: one short sentence
- earliest_start: the earliest time they can play as "HH:MM" if stated, else null
- quote: the exact sentence from the email that states the problem

Email:
{text}

Respond with JSON."""


def parse_change(text: str) -> Change:
    if llm_enabled():
        try:
            out = llm.complete_json(_CHANGE_PROMPT.format(text=text), Change)
            out.reason = clean_text(out.reason)
            return out
        except Exception:
            pass
    return heuristic_change(text)


def heuristic_change(text: str) -> Change:
    lower = text.lower()
    if "cancel" in lower:
        kind = "cancellation"
    elif any(w in lower for w in ("delay", "late", "running behind")):
        kind = "delay"
    elif any(w in lower for w in ("later", "earlier", "move", "swap")):
        kind = "time_change"
    else:
        kind = "other"
    quote = None
    for sentence in re.split(r"(?<=[.!?])\s+|\n", text):
        if re.search(r"cancel|delay|late|later|earlier|move", sentence, re.I):
            quote = sentence.strip()
            break
    earliest = None
    t = re.search(r"(?:land|arriv|earliest)\D{0,30}?(\d{1,2})[:.](\d{2})\s*(pm|am)?", text, re.I)
    if t:
        h, m, ampm = t.groups(default="")
        hour = int(h) % 12 + (12 if ampm.lower() == "pm" else 0) if ampm else int(h)
        earliest = f"{hour:02d}:{m}"
    reason = {
        "cancellation": "Travel cancelled, the artist cannot make the current slot.",
        "delay": "The artist is running late.",
        "time_change": "The artist asked for a different set time.",
        "other": "The artist reported a change.",
    }[kind]
    if earliest:
        reason += f" Earliest they can play is {earliest}."
    return Change(kind=kind, reason=reason, earliest_start=earliest, quote=quote)
