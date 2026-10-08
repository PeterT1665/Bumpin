"""Draft emails for the artist side. Templates follow data/rules/email_policy.md.

Each draft goes through shared draft_email with a templated subject and body
in facts, so drafting works with or without an LLM. Nothing is sent here.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from backend.app.artists import ai
from backend.app.artists._compat import draft_email
from backend.app.shared import llm
from backend.app.shared.rules import load_rules

SIGN_OFF = "Kind regards,\nThe Riverside Festival Team"


def first_name(full: str | None) -> str:
    return (full or "there").split()[0]


def _draft(ticket_id: int, to_addr: str, intent: str, subject: str, body: str,
           context_used: list[str], actor: str, extra: dict | None = None) -> int:
    subject, body, read = polish(subject, body)
    facts = {"subject": subject, "body": body, "context_used": context_used + ["email_policy.md"] + read,
             "actor": actor, **(extra or {})}
    return draft_email(ticket_id, to_addr, intent, facts)


class _Email(BaseModel):
    subject: str
    body: str


_POLISH_PROMPT = """You draft emails for the Riverside festival production team. Rewrite this draft so it reads
naturally and follows the email policy. Keep every name, number, time, date and amount exactly as written,
keep the greeting and the sign-off, and do not promise anything the draft does not. If a reference file the
team uploaded is relevant, you may use it, but never invent facts. Do not use em dashes or en dashes.

Email policy:
{policy}
{notes}
Draft subject: {subject}
Draft body:
{body}

Respond with JSON: {{"subject": "...", "body": "..."}}"""


def polish(subject: str, body: str) -> tuple[str, str, list[str]]:
    """AI wording on top of the template, using the uploaded reference files.

    Kept only if every number and time in the template survives, so a fact can never
    change. Returns the uploaded files the AI read, for context_used."""
    if not ai.llm_enabled():
        return subject, body, []
    notes, names = ai.team_notes()
    try:
        out = llm.complete_json(_POLISH_PROMPT.format(
            policy=load_rules("email_policy"), notes=ai._notes_block(notes), subject=subject, body=body), _Email)
    except Exception:
        return subject, body, []
    facts = set(re.findall(r"\d[\d:,.]*\d|\d", subject + " " + body))
    new_subject, new_body = ai.clean_text(out.subject), ai.clean_text(out.body)
    if not new_body.strip() or any(f not in new_subject + " " + new_body for f in facts):
        return subject, body, []
    return new_subject, new_body, names


def finding_reply(ticket_id: int, artist: dict, finding: dict, actor: str) -> int:
    """Reply to the manager about one rider finding, using the finding's suggestion."""
    asks = {
        "shortage": "We have reviewed your rider and need to check one technical item with you.",
        "double_booking": "We have reviewed your rider and one item from our shared equipment pool is already committed during your set.",
        "over_budget": "We have reviewed the hospitality section of your rider and it is above the allowance for this booking.",
    }
    facts = finding.get("facts") or {}
    if finding["kind"] == "shortage":
        detail = (f"Your rider lists {facts.get('requested')}x {facts.get('item')}, and "
                  f"{facts.get('where')} has {facts.get('available')}. Could you work with "
                  f"{facts.get('available')}, or would you prefer to bring your own?")
    elif finding["kind"] == "double_booking":
        detail = (f"The {facts.get('item')} is booked for another set that overlaps yours. "
                  f"We can look at a later handover time or arrange a hire unit. Which would suit you?")
    elif finding["kind"] == "over_budget":
        detail = (f"The requests come to ${facts.get('total', 0):,.0f} against an allowance of "
                  f"${facts.get('cap', 0):,.0f}. Could you let us know which items matter most so we can "
                  f"agree a list that fits?")
    else:
        detail = finding["message"]
    body = (f"Hi {first_name(artist.get('manager_name'))},\n\n"
            f"{asks.get(finding['kind'], 'We have reviewed your rider and have one question.')}\n\n"
            f"{detail}\n\nLet us know if you have any questions.\n\n{SIGN_OFF}")
    return _draft(ticket_id, artist["manager_email"], f"rider_{finding['kind']}",
                  f"Your rider for Riverside: {facts.get('item') or 'hospitality'}", body,
                  [artist["name"], "rider", finding["kind"]], actor, {"finding": finding["message"]})


def rider_rejection(ticket_id: int, artist: dict, reason: str, actor: str) -> int:
    body = (f"Hi {first_name(artist.get('manager_name'))},\n\n"
            f"Thank you for sending your rider for Riverside. We are not able to confirm it as it stands.\n\n"
            f"{reason.strip().rstrip('.')}.\n\n"
            f"Please send an updated rider and we will be happy to review it. Let us know if you have any questions.\n\n"
            f"{SIGN_OFF}")
    return _draft(ticket_id, artist["manager_email"], "rider_rejection",
                  "Update needed: your rider for Riverside", body, [artist["name"], "rider"], actor,
                  {"reason": reason})


def set_change(ticket_id: int, artist: dict, stage: str, old: str, new: str, end: str, actor: str,
               reason: str) -> int:
    body = (f"Hi {first_name(artist.get('manager_name'))},\n\n"
            f"{reason} your set on {stage} has moved from {old} to {new}, finishing at {end}.\n\n"
            f"Please confirm this works for you. Let us know if you have any questions.\n\n{SIGN_OFF}")
    return _draft(ticket_id, artist["manager_email"], "set_time_change",
                  f"New set time at Riverside: {new} on {stage}", body,
                  [artist["name"], stage, "run sheet"], actor)


def crew_notice(ticket_id: int, to_addr: str, team: str, stage: str, changes: list[str], actor: str,
                context: list[str], note: str = "") -> int:
    lines = "\n".join(f"- {c}" for c in changes)
    note = f"{note}\n\n" if note else ""
    body = (f"Hi {team},\n\nThere is a change to tonight's {stage} schedule:\n\n{lines}\n\n{note}"
            f"Please update your plans and reply if this causes a problem.\n\n{SIGN_OFF}")
    return _draft(ticket_id, to_addr, "schedule_notice", f"{stage} schedule change", body,
                  context + [stage, "run sheet"], actor)
