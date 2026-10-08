"""Vendor eligibility checks. Plain code against data/rules/vendor_eligibility.yaml.

Every comparison here (expiry against the festival end date, insurance cover against
the minimum, document present or not) is a date or number compare, never an LLM guess.
"""

from __future__ import annotations

import re

from backend.app import db
from backend.app.artists.models import Finding
from backend.app.shared.llm import PageText
from backend.app.shared.rules import load_rules
from backend.app.vendors.docs import fmt_date, parse_pages

LABELS = {
    "food_safety": "food safety certificate",
    "insurance": "public liability insurance certificate",
    "permit": "council trading permit",
    "gas": "gas compliance certificate",
}
_PROMISED = re.compile(r"coming|to follow|will (?:send|be sent|forward)|on (?:its|the) way|shortly|this week|soon",
                       re.I)


def _suggestion(kind: str) -> str:
    try:
        return load_rules("actions")[kind]["action"]
    except (FileNotFoundError, KeyError, TypeError):
        return ""


def latest_docs(vendor_id: int) -> dict[str, dict]:
    """Newest document of each kind on file for a vendor."""
    with db.get_conn() as conn:
        docs = db.rows(conn.execute(
            "SELECT * FROM documents WHERE owner_type = 'vendor' AND owner_id = ? ORDER BY id", (vendor_id,)))
    return {d["kind"]: d for d in docs}


def _expiry_line(doc: dict) -> tuple[str | None, int | None]:
    pages = [PageText(page=1, text=doc.get("extracted_text") or "")]
    facts = parse_pages(pages)
    return facts.quote, facts.page


def check_eligibility(vendor_id: int, email_text: str | None = None) -> list[Finding]:
    """Findings for one vendor. email_text, when given, lets the message say what the vendor promised."""
    with db.get_conn() as conn:
        vendor = db.row(conn.execute("SELECT * FROM vendors WHERE id = ?", (vendor_id,)))
    if vendor is None:
        raise KeyError(f"vendor {vendor_id} not found")
    rules = load_rules("vendor_eligibility")
    rule = rules.get(vendor["type"]) or rules["other"]
    end = db.festival()["end_date"]
    end_long = fmt_date(end)
    docs = latest_docs(vendor_id)
    findings: list[Finding] = []

    required = list(rule.get("required_docs", []))
    if vendor["uses_gas"]:
        required += [k for k in rule.get("gas_requires", []) if k not in required]

    for kind in required:
        label = LABELS[kind]
        doc = docs.get(kind)
        if doc is None:
            requirement = (f"Because {vendor['name']} uses gas, we require a {label}." if kind == "gas"
                           else f"We require a {label} for the festival.")
            found = "We do not have one on file."
            msg = f"No {label} on file for {vendor['name']}."
            if kind == "gas" and email_text and "gas" in email_text.lower() and _PROMISED.search(email_text):
                msg = f'The email says the gas certificate is "coming", but no {label} is on file.'
                found = "Your email says it is coming, but we do not have it yet."
            findings.append(Finding(
                kind="missing_doc", severity="conflict", message=msg, suggestion=_suggestion("missing_doc"),
                facts={"doc_kind": kind, "requirement": requirement, "found": found},
            ))
            continue

        expiry = doc["expiry_date"]
        quote, page = _expiry_line(doc)
        if not expiry:
            findings.append(Finding(
                kind="low_confidence", severity="warning",
                message=f"Could not read an expiry date on the {label} ({doc['filename']}).",
                suggestion="Open the document and check the expiry date by hand.",
                doc_id=doc["id"], facts={"doc_kind": kind},
            ))
        elif expiry < end:
            findings.append(Finding(
                kind="expired_cert", severity="conflict",
                message=f"The {label} expires on {fmt_date(expiry)}, before the festival ends on {end_long}.",
                suggestion=_suggestion("expired_cert"),
                doc_id=doc["id"], quote=quote, page=page,
                facts={"doc_kind": kind, "expiry_date": expiry, "festival_end": end,
                       "requirement": f"We require a {label} that is valid through the end of the festival, {end_long}.",
                       "found": f"The one you sent expires on {fmt_date(expiry)}."},
            ))

        if kind == "insurance":
            cover = parse_pages([PageText(page=1, text=doc.get("extracted_text") or "")]).cover_amount
            minimum = int(rule.get("minimum_insurance_cover", 0))
            if cover is not None and cover < minimum:
                findings.append(Finding(
                    kind="missing_doc", severity="conflict",
                    message=f"Insurance cover is ${cover:,}, below the ${minimum:,} minimum for {vendor['type']} vendors.",
                    suggestion=_suggestion("missing_doc"), doc_id=doc["id"],
                    facts={"doc_kind": kind, "cover": cover, "minimum": minimum,
                           "requirement": f"We require public liability cover of at least ${minimum:,}.",
                           "found": f"Your certificate shows ${cover:,}."},
                ))
    return findings
