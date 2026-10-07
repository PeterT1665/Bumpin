"""Draft emails for vendors. Templates follow data/rules/email_policy.md. Nothing is sent here."""

from __future__ import annotations

from backend.app.shared.outbox import SIGN_OFF, draft_email


def first_name(full: str | None) -> str:
    return (full or "there").split()[0]


def rejection_draft(ticket_id: int, vendor: dict, findings: list[dict], doc_names: list[str], actor: str,
                    reason: str = "") -> int:
    """Explain which requirement failed, with the exact requirement and what we found."""
    lines = []
    for f in findings:
        facts = f.get("facts") or {}
        if facts.get("requirement"):
            lines.append(f"- {facts['requirement']} {facts.get('found', '')}".strip())
        else:
            lines.append(f"- {f['message']}")
    extra = f"\n\n{reason.strip().rstrip('.')}." if reason.strip() else ""
    body = (
        f"Hi {first_name(vendor.get('contact_name'))},\n\n"
        f"Thank you for sending your documents for the Riverside Festival. "
        f"We need an update before we can confirm your place.\n\n"
        + "\n".join(lines)
        + extra
        + "\n\nPlease send updated documents and we will be happy to review them. "
          "Let us know if you have any questions.\n\n"
        + SIGN_OFF
    )
    return draft_email(ticket_id, vendor["contact_email"], "vendor_rejection", {
        "subject": "Action required: documents for Riverside",
        "body": body,
        "context_used": [vendor["name"], *doc_names, "vendor_eligibility.yaml", "email_policy.md"],
        "actor": actor,
    })


def load_in_confirmation(ticket_id: int, vendor: dict, old_start: str, new_start: str, new_end: str,
                         actor: str) -> int:
    day = new_start[:10]
    body = (
        f"Hi {first_name(vendor.get('contact_name'))},\n\n"
        f"Thanks for letting us know. Your load-in for the Riverside Festival is now "
        f"{new_start[11:16]} to {new_end[11:16]} on {day} (it was {old_start[11:16]}).\n\n"
        f"Please let us know if anything else changes or if you have any questions.\n\n{SIGN_OFF}"
    )
    return draft_email(ticket_id, vendor["contact_email"], "load_in_confirmation", {
        "subject": "Your Riverside load-in time is updated",
        "body": body,
        "context_used": [vendor["name"], "load-in schedule", "email_policy.md"],
        "actor": actor,
    })


def load_in_notice(ticket_id: int, to_addr: str, audience: str, zone: str, lines: list[str],
                   actor: str, context: list[str]) -> int:
    """Tell someone other than the vendor that a load-in moved.

    A moved load-in has consequences the vendor never sees: the gate has to be
    crewed earlier, the stall next door arrives into a different yard. Those are
    separate approvable steps, so each one gets its own draft rather than being
    folded into the vendor's confirmation.
    """
    body = (
        f"Hi {audience},\n\nThere is a change to the Friday load-in at {zone}:\n\n"
        + "\n".join(f"- {line}" for line in lines)
        + f"\n\nPlease update your plans and reply if this causes a problem.\n\n{SIGN_OFF}"
    )
    return draft_email(ticket_id, to_addr, "load_in_notice", {
        "subject": f"{zone} load-in change",
        "body": body,
        "context_used": [*context, zone, "load-in schedule"],
        "actor": actor,
    })
