"""Draft emails for the artist side. Templates follow data/rules/email_policy.md.

Each draft goes through shared draft_email with a templated subject and body
in facts, so drafting works with or without an LLM. Nothing is sent here.
"""

from __future__ import annotations

from backend.app.artists._compat import draft_email

SIGN_OFF = "Kind regards,\nThe Riverside Festival Team"


def first_name(full: str | None) -> str:
    return (full or "there").split()[0]


def _draft(ticket_id: int, to_addr: str, intent: str, subject: str, body: str,
           context_used: list[str], actor: str, extra: dict | None = None) -> int:
    facts = {"subject": subject, "body": body, "context_used": context_used + ["email_policy.md"],
             "actor": actor, **(extra or {})}
    return draft_email(ticket_id, to_addr, intent, facts)


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
