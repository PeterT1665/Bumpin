"""Read vendor compliance documents: kind, expiry date, issuer, insurance cover.

The parser is plain regex over the PDF text layer, so dates and amounts are never
an LLM guess. An LLM is asked only when the regexes find nothing, and its answer
is checked in code before it is trusted.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel

from backend.app import db
from backend.app.shared import llm
from backend.app.shared.llm import PageText, extract_text

KINDS = ("food_safety", "insurance", "permit", "gas")

_KIND_WORDS = [
    ("gas", re.compile(r"gas (?:compliance|safety|certificate)|lpg", re.I)),
    ("food_safety", re.compile(r"food safety|food premises|food act", re.I)),
    ("insurance", re.compile(r"insurance|certificate of currency|public liability", re.I)),
    ("permit", re.compile(r"permit", re.I)),
]
_EXPIRY = re.compile(
    r"(?P<label>valid until|expiry date|expires|permit expires|policy expiry)\s*:?\s*"
    r"(?P<date>\d{1,2}\s+[A-Za-z]+\s+\d{4}|\d{4}-\d{2}-\d{2})",
    re.I,
)
_ISSUER = re.compile(r"issued by\s*:\s*(.+)", re.I)
_HOLDER = re.compile(r"(?:business name|insured|permit holder|installer for)\s*:\s*(.+)", re.I)
_COVER = re.compile(r"cover\s*:\s*\$\s*([\d,]+)", re.I)


class VendorDocFacts(BaseModel):
    kind: str = "other"
    expiry_date: str | None = None  # ISO date
    issuer: str | None = None
    holder: str | None = None
    cover_amount: int | None = None
    quote: str | None = None  # the exact line the expiry came from
    page: int | None = None


def parse_date(text: str) -> str | None:
    """'5 December 2026' or '2026-12-05' to ISO, else None."""
    text = text.strip()
    for fmt in ("%Y-%m-%d", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def fmt_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day} {d.strftime('%B %Y')}"


def parse_pages(pages: list[PageText]) -> VendorDocFacts:
    """Pure function over page texts. Used at runtime and by the seed generator."""
    full = "\n".join(p.text for p in pages)
    head = "\n".join(full.splitlines()[:4])
    kind = next((k for k, rx in _KIND_WORDS if rx.search(head)), None) or \
        next((k for k, rx in _KIND_WORDS if rx.search(full)), "other")
    facts = VendorDocFacts(kind=kind)
    for p in pages:
        for line in p.text.splitlines():
            m = _EXPIRY.search(line)
            if m and parse_date(m.group("date")):
                facts.expiry_date = parse_date(m.group("date"))
                facts.quote = line.strip()
                facts.page = p.page
                break
        if facts.expiry_date:
            break
    if m := _ISSUER.search(full):
        facts.issuer = m.group(1).strip()
    if m := _HOLDER.search(full):
        facts.holder = m.group(1).strip()
    if m := _COVER.search(full):
        facts.cover_amount = int(m.group(1).replace(",", ""))
    return facts


class _LlmDoc(BaseModel):
    kind: str
    expiry_date: str | None = None
    issuer: str | None = None
    quote: str | None = None


def _llm_enabled() -> bool:
    return (getattr(llm, "_PROVIDER", "fake") or "fake") != "fake"


def _llm_fallback(facts: VendorDocFacts, pages: list[PageText]) -> VendorDocFacts:
    text = "\n".join(f"[page {p.page}]\n{p.text}" for p in pages)[:6000]
    prompt = (
        "Read this vendor compliance document. Return JSON with kind (one of food_safety, insurance, "
        "permit, gas, other), expiry_date as YYYY-MM-DD or null, issuer or null, and quote, the exact "
        "line that states the expiry, or null.\n\n" + text
    )
    try:
        out = llm.complete_json(prompt, _LlmDoc)
    except Exception:
        return facts
    iso = parse_date(out.expiry_date) if out.expiry_date else None
    # Trust the LLM only when its quote really is in the document.
    if iso and out.quote and any(out.quote.strip() in p.text for p in pages):
        facts.expiry_date = iso
        facts.quote = out.quote.strip()
        facts.page = next(p.page for p in pages if out.quote.strip() in p.text)
    if facts.kind == "other" and out.kind in KINDS:
        facts.kind = out.kind
    facts.issuer = facts.issuer or out.issuer
    return facts


def resolve_path(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else db.ROOT / p


def extract_vendor_doc(doc_id: int) -> VendorDocFacts:
    """Read a stored document, save kind, expiry, issuer and text on its row, return the facts."""
    with db.get_conn() as conn:
        doc = db.row(conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)))
    if doc is None:
        raise KeyError(f"document {doc_id} not found")
    path = resolve_path(doc["path"]) if doc["path"] else None
    if path is not None and path.exists():
        pages = extract_text(str(path))
    else:
        pages = [PageText(page=1, text=doc["extracted_text"] or "")]
    facts = parse_pages(pages)
    if _llm_enabled() and not facts.expiry_date:
        facts = _llm_fallback(facts, pages)
    with db.get_conn() as conn:
        conn.execute(
            """UPDATE documents SET kind = ?, expiry_date = ?, issuer = ?,
                   extracted_text = ? WHERE id = ?""",
            (facts.kind if facts.kind != "other" else doc["kind"], facts.expiry_date, facts.issuer,
             "\n".join(p.text for p in pages), doc_id),
        )
    return facts
