"""Vendor tickets (type vendor_eligibility): document checks and load-in changes.

A document ticket carries findings from check_eligibility and, when a requirement fails,
a drafted email recommending rejection. A change ticket carries one proposed action that
only edits the vendor's load-in time after a human approves it. Nothing here sends.
"""

from __future__ import annotations

import json
import re
from datetime import datetime

from pydantic import BaseModel

from backend.app import db
from backend.app.artists.tickets import SEVERITY_RANK, RiderBlocked, insert_finding
from backend.app.shared import llm
from backend.app.shared.decisions import AlreadyDecided, audit, decide, now
from backend.app.shared.notifications import notify
from backend.app.shared.registry import register_handler
from backend.app.vendors import emails
from backend.app.vendors.docs import extract_vendor_doc
from backend.app.vendors.eligibility import check_eligibility

REVIEW_CONFIDENCE = 0.60
WEEKDAYS = {"friday": "2026-12-11", "saturday": "2026-12-12", "sunday": "2026-12-13"}


class VendorBlocked(RiderBlocked):
    """Approve attempted with an open conflict and no override reason. The router maps this to 409."""


def other_user(actor: str) -> str:
    return "jess" if actor == "ravi" else "ravi"


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower().replace("&", "and")).strip()


def find_vendor(email: dict, classification) -> dict | None:
    with db.get_conn() as conn:
        if email.get("from_addr"):
            v = db.row(conn.execute("SELECT * FROM vendors WHERE lower(contact_email) = lower(?)",
                                    (email["from_addr"],)))
            if v:
                return v
        hint = getattr(classification, "entity_hint", None)
        if hint:
            for v in db.rows(conn.execute("SELECT * FROM vendors")):
                if _norm(v["name"]) == _norm(hint):
                    return v
    return None


def _email(email_id: int) -> dict:
    with db.get_conn() as conn:
        email = db.row(conn.execute("SELECT * FROM emails WHERE id = ?", (email_id,)))
    if email is None:
        raise KeyError(f"email {email_id} not found")
    return email


def _review_ticket(email: dict, vendor: dict | None, message: str, suggestion: str) -> int:
    """Acknowledge-only ticket (empty proposed actions) for mail BumpIn could not act on."""
    who = vendor["name"] if vendor else (email.get("from_addr") or "unknown sender")
    snippet = " ".join((email.get("body") or "").split())[:200]
    with db.get_conn() as conn:
        tid = conn.execute(
            """INSERT INTO tickets (type, owner_type, owner_id, status, severity, summary,
                                    proposed_actions_json, created_at, updated_at)
               VALUES ('vendor_eligibility', 'vendor', ?, 'needs_review', 'warning', ?, '[]', ?, ?)""",
            (vendor["id"] if vendor else None, f"{who}: {message}", now(), now()),
        ).lastrowid
        conn.execute(
            """INSERT INTO findings (ticket_id, kind, severity, message, suggestion, quote, status)
               VALUES (?, 'low_confidence', 'warning', ?, ?, ?, 'open')""",
            (tid, message, suggestion, snippet),
        )
        conn.execute("UPDATE emails SET ticket_id = ? WHERE id = ?", (tid, email["id"]))
        audit(conn, tid, "system", "ticket_created", {"type": "vendor_eligibility", "review": True})
    return tid


# --- document tickets -----------------------------------------------------------------------

def create_vendor_ticket(email_id: int, classification) -> int:
    """Called by the inbox pipeline for label 'vendor_doc'. Returns the ticket id."""
    email = _email(email_id)
    vendor = find_vendor(email, classification)
    if vendor is None:
        return _review_ticket(email, None, "documents received but the vendor could not be identified.",
                              "Match this email to a vendor by hand.")

    with db.get_conn() as conn:
        doc_ids = [r[0] for r in conn.execute("SELECT id FROM documents WHERE email_id = ?", (email_id,))]
        for doc_id in doc_ids:
            conn.execute("UPDATE documents SET owner_type = 'vendor', owner_id = ? WHERE id = ?",
                         (vendor["id"], doc_id))
    for doc_id in doc_ids:
        extract_vendor_doc(doc_id)

    text = f"{email.get('subject') or ''}\n{email.get('body') or ''}"
    found = check_eligibility(vendor["id"], text)

    with db.get_conn() as conn:
        ticket = db.row(conn.execute(
            """SELECT * FROM tickets WHERE type = 'vendor_eligibility' AND owner_type = 'vendor'
               AND owner_id = ? AND proposed_actions_json IS NULL""", (vendor["id"],)))
        status = "needs_review" if found else "open"  # any finding is about a critical field
        severity = max((f.severity for f in found), key=SEVERITY_RANK.get, default="info")
        top = max(found, key=lambda f: SEVERITY_RANK[f.severity], default=None)
        summary = f"{vendor['name']}: {top.message}" if top else \
            f"{vendor['name']}: documents received, no problems found"
        if ticket:
            tid = ticket["id"]
            conn.execute("DELETE FROM findings WHERE ticket_id = ?", (tid,))
            conn.execute("DELETE FROM outbox WHERE ticket_id = ? AND status = 'draft' AND created_by = 'system'",
                         (tid,))
            conn.execute(
                """UPDATE tickets SET status = ?, severity = ?, summary = ?, decided_by = NULL,
                       decided_at = NULL, updated_at = ? WHERE id = ?""",
                (status, severity, summary, now(), tid))
            if vendor["status"] == "rejected":
                conn.execute("UPDATE vendors SET status = 'in_progress' WHERE id = ?", (vendor["id"],))
            audit(conn, tid, "system", "ticket_reopened", "New documents received")
        else:
            tid = conn.execute(
                """INSERT INTO tickets (type, owner_type, owner_id, status, severity, summary, created_at, updated_at)
                   VALUES ('vendor_eligibility', 'vendor', ?, ?, ?, ?, ?, ?)""",
                (vendor["id"], status, severity, summary, now(), now())).lastrowid
            audit(conn, tid, "system", "ticket_created", {"type": "vendor_eligibility", "docs": len(doc_ids)})
        for f in found:
            insert_finding(conn, tid, f)
        conn.execute("UPDATE emails SET ticket_id = ? WHERE id = ?", (tid, email_id))

    if any(f.severity == "conflict" for f in found):
        recommend_rejection(vendor["id"])
    return tid


def recommend_rejection(vendor_id: int, actor: str = "system", reason: str = "") -> int:
    """Draft the email explaining which requirements failed. Never sends, never changes a status."""
    with db.get_conn() as conn:
        vendor = db.row(conn.execute("SELECT * FROM vendors WHERE id = ?", (vendor_id,)))
        if vendor is None:
            raise KeyError(f"vendor {vendor_id} not found")
        ticket = db.row(conn.execute(
            """SELECT * FROM tickets WHERE type = 'vendor_eligibility' AND owner_type = 'vendor'
               AND owner_id = ? AND proposed_actions_json IS NULL ORDER BY id DESC LIMIT 1""", (vendor_id,)))
        if ticket is None:
            raise KeyError(f"vendor {vendor_id} has no eligibility ticket")
        findings = db.rows(conn.execute(
            """SELECT * FROM findings WHERE ticket_id = ? AND severity = 'conflict' AND status = 'open'
               ORDER BY id""", (ticket["id"],)))
        docs = [r[0] for r in conn.execute(
            "SELECT filename FROM documents WHERE owner_type = 'vendor' AND owner_id = ? ORDER BY id", (vendor_id,))]
    if not findings:
        raise ValueError("Nothing to reject: this vendor has no open conflicts.")
    for f in findings:
        f["facts"] = json.loads(f["bbox_json"]).get("facts", {}) if f["bbox_json"] else {}
    return emails.rejection_draft(ticket["id"], vendor, findings, docs, actor, reason)


# --- change tickets (problem 8) ---------------------------------------------------------------

class LoadInChange(BaseModel):
    new_start: str  # ISO
    new_end: str
    quote: str


class _LlmChange(BaseModel):
    new_start_time: str | None = None  # HH:MM 24h
    day: str | None = None  # friday, saturday or sunday


_TIME = re.compile(r"\b(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)\b|\b(\d{1,2})[:.](\d{2})\b", re.I)


def _times(sentence: str) -> list[tuple[int, int]]:
    out = []
    for m in _TIME.finditer(sentence):
        if m.group(3):
            h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3).lower()
            h = h % 12 + (12 if ap == "pm" else 0)
        else:
            h, mi = int(m.group(4)), int(m.group(5))
        if 0 <= h < 24 and 0 <= mi < 60:
            out.append((h, mi))
    return out


def parse_load_in_change(text: str, vendor: dict) -> LoadInChange | None:
    """New load-in start, read in plain code. The old window's length is kept."""
    old_start = datetime.fromisoformat(vendor["load_in_start"])
    length = datetime.fromisoformat(vendor["load_in_end"]) - old_start
    day = old_start.date().isoformat()
    for word, iso in WEEKDAYS.items():
        if word in text.lower():
            day = iso
            break
    quote, new = None, None
    for sentence in re.split(r"(?<=[.!?])\s+|\n", text):
        if re.search(r"load[- ]?in|arrive|arrival|setup|set up", sentence, re.I):
            times = _times(sentence)
            if times:
                quote, new = sentence.strip(), times[-1]  # "from 7am to 5:30am": the last one is new
                break
    if new is None and llm._PROVIDER not in ("", "fake"):
        try:
            out = llm.complete_json(
                "A vendor emailed about changing their load-in time. Return JSON {\"new_start_time\": "
                "\"HH:MM\" 24 hour or null, \"day\": \"friday\"|\"saturday\"|\"sunday\" or null}.\n\n" + text,
                _LlmChange)
            m = re.fullmatch(r"(\d{1,2}):(\d{2})", out.new_start_time or "")
            if m:
                new, quote = (int(m.group(1)), int(m.group(2))), text.strip().splitlines()[0][:200]
                day = WEEKDAYS.get((out.day or "").lower(), day)
        except Exception:
            pass
    if new is None:
        return None
    start = datetime.fromisoformat(f"{day}T{new[0]:02d}:{new[1]:02d}:00")
    return LoadInChange(new_start=start.isoformat(), new_end=(start + length).isoformat(), quote=quote or "")


def _hhmm(ts: str) -> str:
    return ts[11:16]


def create_vendor_change_ticket(email_id: int, classification) -> int:
    """Called by the inbox pipeline for 'help_or_change' from a vendor. Returns the ticket id."""
    email = _email(email_id)
    vendor = find_vendor(email, classification)
    if vendor is None:
        return _review_ticket(email, None, "change request received but the vendor could not be identified.",
                              "Match this email to a vendor by hand.")
    confidence = getattr(classification, "confidence", 1.0)
    text = f"{email.get('subject') or ''}\n{email.get('body') or ''}"
    change = None if confidence < REVIEW_CONFIDENCE else parse_load_in_change(text, vendor)
    if change is None:
        return _review_ticket(
            email, vendor,
            "unclear request, needs a human." if confidence < REVIEW_CONFIDENCE
            else "asked for a change, but BumpIn could not tell what the new load-in time is.",
            "Reply and ask for the exact time they need.")

    day = datetime.fromisoformat(change.new_start).strftime("%A")
    reason = (f"{vendor['name']} asks to move load-in from {_hhmm(vendor['load_in_start'])} "
              f"to {_hhmm(change.new_start)} on {day}.")
    action = {
        "index": 0, "kind": "move_load_in",
        "title": f"Move {vendor['name']} load-in to {_hhmm(change.new_start)}",
        "detail": f"From {_hhmm(vendor['load_in_start'])} to {_hhmm(change.new_start)}. Approving updates "
                  f"the run sheet and drafts a confirmation to {vendor['contact_email']}.",
        "to_addr": vendor["contact_email"], "vendor_id": vendor["id"],
        "new_start": change.new_start, "new_end": change.new_end,
        "status": "proposed", "approved_by": None, "outbox_id": None,
    }
    facts = {"vendor_id": vendor["id"], "old_start": vendor["load_in_start"], "old_end": vendor["load_in_end"],
             "new_start": change.new_start, "new_end": change.new_end}
    with db.get_conn() as conn:
        tid = conn.execute(
            """INSERT INTO tickets (type, owner_type, owner_id, status, severity, summary,
                                    proposed_actions_json, created_at, updated_at)
               VALUES ('vendor_eligibility', 'vendor', ?, 'needs_review', 'warning', ?, ?, ?, ?)""",
            (vendor["id"], f"{vendor['name']}: {reason}", json.dumps([action]), now(), now())).lastrowid
        conn.execute(
            """INSERT INTO findings (ticket_id, kind, severity, message, suggestion, quote, status, bbox_json)
               VALUES (?, 'schedule_change', 'warning', ?, ?, ?, 'open', ?)""",
            (tid, reason, "Review the proposed change. The load-in time only changes when you approve.",
             change.quote, json.dumps({"facts": facts})))
        conn.execute("UPDATE emails SET ticket_id = ?, is_major_change = 1 WHERE id = ?", (tid, email_id))
        audit(conn, tid, "system", "ticket_created", {"type": "vendor_eligibility", "change": "load_in"})
    return tid


# --- handler ----------------------------------------------------------------------------------

def _ticket(conn, ticket_id: int) -> dict:
    t = db.row(conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)))
    if t is None:
        raise KeyError(f"ticket {ticket_id} not found")
    return t


def _actions(t: dict) -> list[dict] | None:
    return json.loads(t["proposed_actions_json"]) if t["proposed_actions_json"] is not None else None


def _save_actions(conn, ticket_id: int, actions: list[dict]) -> None:
    conn.execute("UPDATE tickets SET proposed_actions_json = ?, updated_at = ? WHERE id = ?",
                 (json.dumps(actions), now(), ticket_id))


def _apply_action(ticket_id: int, index: int, actor: str) -> int:
    """Apply one action, draft its email, mark it approved. Returns the outbox id.

    `move_load_in` is the only kind that writes to the run sheet. The knock-on
    steps a moved load-in creates (crewing the gate earlier, warning the stall
    next door) are `notify` actions: they draft a message and change nothing, so
    turning one down costs the site nothing.
    """
    with db.get_conn() as conn:
        t = _ticket(conn, ticket_id)
        actions = _actions(t) or []
        if not 0 <= index < len(actions):
            raise KeyError(f"action {index} not on ticket {ticket_id}")
        a = actions[index]
        if a["status"] != "proposed":
            raise AlreadyDecided(a["approved_by"], t["updated_at"])
        vendor = db.row(conn.execute("SELECT * FROM vendors WHERE id = ?", (a["vendor_id"],)))
        old_start = vendor["load_in_start"]
        if a["kind"] == "move_load_in":
            conn.execute("UPDATE vendors SET load_in_start = ?, load_in_end = ? WHERE id = ?",
                         (a["new_start"], a["new_end"], vendor["id"]))
            audit(conn, ticket_id, actor, "load_in_changed",
                  {"vendor": vendor["name"], "from": old_start, "to": a["new_start"]})
        else:
            audit(conn, ticket_id, actor, "action_approved", {"index": index, "title": a["title"]})
    if a["kind"] == "move_load_in":
        outbox_id = emails.load_in_confirmation(ticket_id, vendor, old_start, a["new_start"], a["new_end"], actor)
    else:
        # `detail` is card copy and ends in "drafts to ...", which is a note to
        # the operator, not to the recipient; `lines` is what the notice says.
        outbox_id = emails.load_in_notice(ticket_id, a["to_addr"], a.get("audience") or "team",
                                          vendor["site_zone"], a.get("lines") or [a["detail"]],
                                          actor, [vendor["name"]])
    with db.get_conn() as conn:
        actions = _actions(_ticket(conn, ticket_id))
        actions[index].update(status="approved", approved_by=actor, outbox_id=outbox_id)
        _save_actions(conn, ticket_id, actions)
        # A denied row is decided too, so the ticket closes on the last verdict
        # rather than waiting for an approval that is never coming.
        if all(x["status"] != "proposed" for x in actions):
            conn.execute("UPDATE tickets SET status = 'resolved' WHERE id = ?", (ticket_id,))
            conn.execute("UPDATE findings SET status = 'resolved' WHERE ticket_id = ? AND status = 'open'",
                         (ticket_id,))
        else:
            conn.execute("UPDATE tickets SET status = 'in_progress' WHERE id = ?", (ticket_id,))
    notify(other_user(actor), ticket_id,
           f"{actor.title()} approved: {a['title']}. Confirmation drafted to {a['to_addr']}.")
    return outbox_id


def _refresh_status(conn, ticket_id: int) -> None:
    t = _ticket(conn, ticket_id)
    if t["status"] in ("approved", "rejected", "resolved"):
        return
    open_n = conn.execute("SELECT COUNT(*) FROM findings WHERE ticket_id = ? AND status = 'open'",
                          (ticket_id,)).fetchone()[0]
    conn.execute("UPDATE tickets SET status = ?, updated_at = ? WHERE id = ?",
                 ("needs_review" if open_n else "in_progress", now(), ticket_id))


class VendorHandler:
    def approve(self, ticket_id: int, actor: str, payload: dict | None) -> None:
        with db.get_conn() as conn:
            t = _ticket(conn, ticket_id)
            conflicts = conn.execute(
                "SELECT COUNT(*) FROM findings WHERE ticket_id = ? AND status = 'open' AND severity = 'conflict'",
                (ticket_id,)).fetchone()[0]
        if t["decided_by"]:
            raise AlreadyDecided(t["decided_by"], t["decided_at"])
        override = ((payload or {}).get("override_reason") or "").strip()
        actions = _actions(t)
        if actions is None and conflicts and not override:
            raise VendorBlocked(f"{conflicts} open conflict(s). Resolve them or give an override reason.")
        decide(ticket_id, actor, "approve", payload)

        if actions is None:  # document ticket: the vendor is cleared
            with db.get_conn() as conn:
                conn.execute("UPDATE tickets SET status = 'approved', updated_at = ? WHERE id = ?", (now(), ticket_id))
                if t["owner_id"]:
                    conn.execute("UPDATE vendors SET status = 'completed' WHERE id = ?", (t["owner_id"],))
                audit(conn, ticket_id, actor, "vendor_approved", {"override_reason": override} if override else {})
            notify(other_user(actor), ticket_id, f"{actor.title()} approved the documents. {t['summary']}")
            return
        for a in actions:
            if a["status"] == "proposed":
                _apply_action(ticket_id, a["index"], actor)
        with db.get_conn() as conn:
            conn.execute("UPDATE tickets SET status = 'resolved', updated_at = ? WHERE id = ?", (now(), ticket_id))
            conn.execute("UPDATE findings SET status = 'resolved' WHERE ticket_id = ? AND status = 'open'",
                         (ticket_id,))

    def reject(self, ticket_id: int, actor: str, reason: str) -> None:
        decide(ticket_id, actor, "reject", {"reason": reason})
        with db.get_conn() as conn:
            t = _ticket(conn, ticket_id)
            has_draft = conn.execute("SELECT COUNT(*) FROM outbox WHERE ticket_id = ? AND status = 'draft'",
                                     (ticket_id,)).fetchone()[0]
            conn.execute("UPDATE tickets SET status = 'rejected', updated_at = ? WHERE id = ?", (now(), ticket_id))
            if _actions(t) is None and t["owner_id"]:
                conn.execute("UPDATE vendors SET status = 'rejected' WHERE id = ?", (t["owner_id"],))
            audit(conn, ticket_id, actor, "vendor_rejected", {"reason": reason})
        if _actions(t) is None and t["owner_id"] and not has_draft:
            try:
                recommend_rejection(t["owner_id"], actor, reason)
            except ValueError:
                pass  # no open conflict to explain, the human's reason stands alone
        notify(other_user(actor), ticket_id, f"{actor.title()} rejected: {t['summary']}. A reply is drafted.")

    def resolve_finding(self, ticket_id: int, finding_id: int, actor: str) -> None:
        self._set_finding(ticket_id, finding_id, actor, "resolve_finding", "resolved")

    def ignore_finding(self, ticket_id: int, finding_id: int, actor: str) -> None:
        self._set_finding(ticket_id, finding_id, actor, "ignore_finding", "ignored")

    def _set_finding(self, ticket_id: int, finding_id: int, actor: str, action: str, status: str) -> None:
        decide(ticket_id, actor, action, {"finding_id": finding_id})
        with db.get_conn() as conn:
            cur = conn.execute("UPDATE findings SET status = ? WHERE id = ? AND ticket_id = ?",
                               (status, finding_id, ticket_id))
            if cur.rowcount == 0:
                raise KeyError(f"finding {finding_id} not on ticket {ticket_id}")
            _refresh_status(conn, ticket_id)

    def approve_action(self, ticket_id: int, index: int, actor: str) -> None:
        with db.get_conn() as conn:
            if _actions(_ticket(conn, ticket_id)) is None:
                raise ValueError("Document tickets have no proposed actions.")
        decide(ticket_id, actor, "approve_action", {"index": index})
        _apply_action(ticket_id, index, actor)

    def deny_action(self, ticket_id: int, index: int, actor: str) -> None:
        """Turn one proposed step down. The quiet mirror of approve_action:
        nothing moves on the run sheet and no email is drafted, so saying no to
        a consequence costs nobody a message. A document ticket has no steps to
        turn down, which is a different refusal from an unknown index."""
        with db.get_conn() as conn:
            t = _ticket(conn, ticket_id)
            actions = _actions(t)
            if actions is None:
                raise ValueError("Document tickets have no proposed actions.")
            if not 0 <= index < len(actions):
                raise KeyError(f"action {index} not on ticket {ticket_id}")
            a = actions[index]
            if a["status"] != "proposed":
                raise AlreadyDecided(a["approved_by"], t["updated_at"])
            a.update(status="denied", approved_by=actor)
            _save_actions(conn, ticket_id, actions)
            if all(x["status"] != "proposed" for x in actions):
                conn.execute("UPDATE tickets SET status = 'resolved' WHERE id = ?", (ticket_id,))
                conn.execute("UPDATE findings SET status = 'resolved' WHERE ticket_id = ? AND status = 'open'",
                             (ticket_id,))
            else:
                conn.execute("UPDATE tickets SET status = 'in_progress' WHERE id = ?", (ticket_id,))
            audit(conn, ticket_id, actor, "action_denied", {"index": index, "title": a["title"]})
        notify(other_user(actor), ticket_id, f"{actor.title()} turned down: {a['title']}.")

    def edit_action(self, ticket_id: int, index: int, actor: str, edits: dict) -> None:
        with db.get_conn() as conn:
            t = _ticket(conn, ticket_id)
            actions = _actions(t)
            if actions is None:
                raise ValueError("Document tickets have no proposed actions.")
            if not 0 <= index < len(actions):
                raise KeyError(f"action {index} not on ticket {ticket_id}")
            a = actions[index]
            if a["status"] == "approved":
                raise ValueError("This action is already approved.")
            for key in ("new_start", "new_end", "to_addr", "detail", "title"):
                if key in edits:
                    a[key] = edits[key]
            # Only a move carries times; a notify step has none to validate.
            if a["kind"] == "move_load_in":
                if "new_start" in edits and "new_end" not in edits:
                    v = db.row(conn.execute("SELECT load_in_start, load_in_end FROM vendors WHERE id = ?",
                                            (a["vendor_id"],)))
                    length = datetime.fromisoformat(v["load_in_end"]) - datetime.fromisoformat(v["load_in_start"])
                    a["new_end"] = (datetime.fromisoformat(a["new_start"]) + length).isoformat()
                try:
                    datetime.fromisoformat(a["new_start"]), datetime.fromisoformat(a["new_end"])
                except ValueError:
                    raise ValueError("new_start and new_end must be ISO timestamps.")
            if a["kind"] == "move_load_in" and "title" not in edits and "new_start" in edits:
                a["title"] = a["title"].rsplit(" to ", 1)[0] + f" to {_hhmm(a['new_start'])}"
            _save_actions(conn, ticket_id, actions)
        decide(ticket_id, actor, "edit_action", {"index": index, "edits": edits})


register_handler("vendor_eligibility", VendorHandler())
