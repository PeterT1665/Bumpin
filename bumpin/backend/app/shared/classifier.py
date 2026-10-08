"""Email classifier.

With JEV_API_KEY set, TypeSafe's Jev model decides (shared/jev.py): the label is a choice
question and its confidence comes from Jev's probability spread. Otherwise, or if Jev fails,
two independent LLM calls with enum-constrained output are used. If the labels differ,
confidence = min(confidence, 0.5), else the mean of the two. With no LLM at all, keyword rules.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

from backend.app.shared import jev
from backend.app.shared.llm import complete_json


class Classification(BaseModel):
    label: Literal["rider", "vendor_doc", "help_or_change", "unsure"]
    confidence: float  # 0 to 1
    reason: str
    sender_role: Literal["artist", "vendor", "unknown"]
    entity_hint: str | None  # artist or vendor name if found
    is_major_change: bool


class _SingleClassification(BaseModel):
    """Schema for a single classifier LLM call."""
    label: Literal["rider", "vendor_doc", "help_or_change", "unsure"]
    confidence: float
    reason: str
    sender_role: Literal["artist", "vendor", "unknown"]
    entity_hint: str | None
    is_major_change: bool


_CLASSIFY_PROMPT = """You are classifying an inbound email for BumpIn, a festival vendor and artist CRM.

Classify this email into exactly one category:
- "rider": an artist sending their technical or hospitality rider (PDF, list of equipment, stage needs)
- "vendor_doc": a vendor submitting documents (permits, food safety certificates, insurance, gas certificates)
- "help_or_change": a request for help, a schedule change, a cancellation, or a question about logistics
- "unsure": you cannot confidently determine the category

Also determine:
- sender_role: "artist" if the sender is an artist or their manager, "vendor" if a vendor, "unknown" otherwise
- entity_hint: the name of the artist or vendor if you can identify them, or null
- is_major_change: true if this involves a set time change, cancellation, stage change, equipment quantity change, vendor withdrawal, or load-in time change
- confidence: 0 to 1, how confident you are in the label
- reason: a short explanation of why you chose this label

Respond with valid JSON matching this schema:
{{"label": "...", "confidence": 0.0, "reason": "...", "sender_role": "...", "entity_hint": "..." or null, "is_major_change": false}}

Email text:
---
{text}
---"""


# A change request with hedging words and no concrete time or firm event is too vague to
# act on, whatever the model says about its own confidence. Plain code, not an LLM guess.
VAGUE_CONFIDENCE_CAP = 0.5
_HEDGE = re.compile(
    r"\b(maybe|perhaps|possibly|a bit|a little|wondering|any flexibility|could we|can we|"
    r"would it be possible|at some point|sometime)\b", re.I)
_CLOCK = re.compile(r"\b\d{1,2}[:.]\d{2}\b|\b\d{1,2}\s?(?:am|pm)\b|\b(?:noon|midnight)\b", re.I)
_FIRM = re.compile(r"\b(cancel\w*|withdraw\w*|delayed|stranded|unable to|cannot make|can't make)\b", re.I)


def is_vague_change(text: str) -> bool:
    return bool(_HEDGE.search(text)) and not _CLOCK.search(text) and not _FIRM.search(text)


_RIDER_WORDS = re.compile(r"\brider\b|\btech(nical)? spec|\bhospo\b|\bhospitality\b", re.I)
_DOC_WORDS = re.compile(
    r"certificate|permit|insurance|public liability|food safety|gas safety|compliance", re.I)
_CHANGE_WORDS = re.compile(
    r"cancel|flight|delayed|running behind|moving|move (?:our|the|my)|load[- ]?in|re-?scheduled?|"
    r"stage change|pulling out|withdraw", re.I)
_VAGUE_WORDS = re.compile(r"could we|can we|maybe|a bit|later|earlier|change|question|wondering|swap", re.I)
_MAJOR_WORDS = re.compile(
    r"cancel|flight|delayed|moving|move (?:our|the|my)|load[- ]?in|re-?scheduled?|stage change|"
    r"pulling out|withdraw", re.I)
_HAS_TIME = re.compile(r"\b\d{1,2}[:.]\d{2}\b|\b\d{1,2}\s?(?:am|pm)\b", re.I)


def heuristic_classify(text: str) -> Classification:
    """Keyword rules used when no LLM is available. Same output shape as classify()."""
    has_attachment = "[attachment" in text.lower()
    if _RIDER_WORDS.search(text):
        label, conf, why = "rider", 0.95, "Mentions a rider or hospitality list."
    elif has_attachment and _DOC_WORDS.search(text):
        label, conf, why = "vendor_doc", 0.95, "Attached compliance documents."
    elif _CHANGE_WORDS.search(text) and (_HAS_TIME.search(text) or re.search(r"cancel", text, re.I)):
        label, conf, why = "help_or_change", 0.92, "Reports a concrete change or cancellation."
    elif _VAGUE_WORDS.search(text):
        label, conf, why = "help_or_change", 0.45, "Asks for a change but gives no specific time or reason."
    elif _DOC_WORDS.search(text):
        label, conf, why = "vendor_doc", 0.7, "Talks about compliance documents but none are attached."
    else:
        label, conf, why = "unsure", 0.3, "Could not tell what this email is about."
    major = label == "help_or_change" and conf >= 0.9 and bool(_MAJOR_WORDS.search(text))
    return Classification(
        label=label, confidence=conf, reason=f"Keyword fallback. {why}",
        sender_role="unknown", entity_hint=None, is_major_change=major,
    )


def _jev_classify(text: str) -> Classification:
    answers = jev.evaluate(text)
    label = answers["label"]
    role = answers["sender_role"]["choice"]
    major = answers["is_major_change"]["noul"] >= 0.5
    # The keyword rules only supply a hint for the entity name; the address book overrides it later.
    return Classification(
        label=label["choice"],
        confidence=round(float(label["confidence"]), 3),
        reason=f"Jev chose {label['choice']} ({label['probabilities'][label['choice']]:.2f}).",
        sender_role=role,
        entity_hint=None,
        is_major_change=major,
    )


def classify(text: str) -> Classification:
    """Jev when a key is set, else the two-pass LLM check, else keyword rules."""
    if jev.enabled():
        try:
            return _cap_vague(_jev_classify(text), text)
        except Exception:
            pass  # network, auth, rate limit or an unexpected reply: fall through
    return _classify_llm(text)


def _cap_vague(cls: Classification, text: str) -> Classification:
    """Same code rule for every classifier: a vague change request is never auto-filed."""
    if cls.label == "help_or_change" and is_vague_change(text) and cls.confidence > VAGUE_CONFIDENCE_CAP:
        return cls.model_copy(update={
            "confidence": VAGUE_CONFIDENCE_CAP,
            "reason": f"Vague change request with no concrete time, needs a human. {cls.reason}",
        })
    return cls


def _classify_llm(text: str) -> Classification:
    """Classify an email using two independent LLM calls for agreement checking."""
    prompt_a = _CLASSIFY_PROMPT.format(text=text)
    prompt_b = "SECOND INDEPENDENT PASS. " + prompt_a

    try:
        result_a = complete_json(prompt_a, _SingleClassification, cache_key=None)
        result_b = complete_json(prompt_b, _SingleClassification, cache_key=None)
    except Exception:
        # No provider key, or the reply did not validate. Fall back to keyword rules.
        return heuristic_classify(text)

    # Agreement check
    if result_a.label != result_b.label:
        # Labels differ: use the first label but cap confidence at 0.5
        confidence = min(result_a.confidence, 0.5)
        label = result_a.label
        reason = (
            f"Disagreement between passes ('{result_a.label}' vs '{result_b.label}'). "
            f"Using first pass. {result_a.reason}"
        )
    else:
        # Labels agree: use the mean confidence
        confidence = (result_a.confidence + result_b.confidence) / 2.0
        label = result_a.label
        reason = result_a.reason

    # Merge is_major_change: true if either pass says true
    is_major = result_a.is_major_change or result_b.is_major_change

    # Use the entity hint from whichever pass found one
    entity_hint = result_a.entity_hint or result_b.entity_hint

    # Use the sender role from the first pass, unless unknown
    sender_role = result_a.sender_role
    if sender_role == "unknown":
        sender_role = result_b.sender_role

    if label == "help_or_change" and is_vague_change(text) and confidence > VAGUE_CONFIDENCE_CAP:
        confidence = VAGUE_CONFIDENCE_CAP
        reason = f"Vague change request with no concrete time, needs a human. {reason}"

    return Classification(
        label=label,
        confidence=round(confidence, 3),
        reason=reason,
        sender_role=sender_role,
        entity_hint=entity_hint,
        is_major_change=is_major,
    )
