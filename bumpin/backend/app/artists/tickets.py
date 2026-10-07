"""Rider tickets: creation from the inbox, approve with allocation, reject, finding actions."""

from __future__ import annotations

import json

from backend.app import db
from backend.app.artists import checks, emails, riders
from backend.app.artists._compat import (
    AlreadyDecided, audit, decide, notify, now, other_user, register_handler,
)
from backend.app.artists.models import Finding

SEVERITY_RANK = {"conflict": 3, "warning": 2, "info": 1}
AUTO_FILE_CONFIDENCE = 0.90


class RiderBlocked(ValueError):
    """Approve attempted while a conflict is open and no override reason was given."""


def _norm_name(name: str) -> str:
    return name.lower().replace("&", "and").replace("  ", " ").strip()


def find_artist(email: dict, classification) -> dict | None:
    with db.get_conn() as conn:
        if email.get("from_addr"):
            a = db.row(conn.execute("SELECT * FROM artists WHERE lower(manager_email) = lower(?)",
                                    (email["from_addr"],)))
            if a:
                return a
        hint = getattr(classification, "entity_hint", None)
        if hint:
            for a in db.rows(conn.execute("SELECT * FROM artists")):
                if _norm_name(a["name"]) == _norm_name(hint):
                    return a
    return None


# --- creation -----------------------------------------------------------------------

def create_rider_ticket(email_id: int, classification) -> int:
    """Called by the inbox pipeline for label 'rider'. Returns the ticket id."""
    with db.get_conn() as conn:
        email = db.row(conn.execute("SELECT * FROM emails WHERE id = ?", (email_id,)))
    if email is None:
        raise KeyError(f"email {email_id} not found")
    artist = find_artist(email, classification)
    confidence = getattr(classification, "confidence", 1.0)
    if artist is None:
        return _unmatched_ticket(email, "rider", "Rider received but the artist could not be identified.")

    with db.get_conn() as conn:
        docs = db.rows(conn.execute("SELECT * FROM documents WHERE email_id = ?", (email_id,)))
        doc_ids = []
        for d in docs:
            conn.execute("UPDATE documents SET owner_type = 'artist', owner_id = ?, kind = 'rider' WHERE id = ?",
                         (artist["id"], d["id"]))
            doc_ids.append(d["id"])
        if not doc_ids:
            # Rider pasted into the email body.
            cur = conn.execute(
                """INSERT INTO documents (owner_type, owner_id, kind, filename, path, extracted_text,
                                          received_at, email_id)
                   VALUES ('artist', ?, 'rider', ?, '', ?, ?, ?)""",
                (artist["id"], f"email_{email_id}.txt", email["body"] or "", now(), email_id),
            )
            doc_ids.append(int(cur.lastrowid))

    ticket_id = process_rider(artist["id"], doc_ids, confidence=confidence)
    with db.get_conn() as conn:
        conn.execute("UPDATE emails SET ticket_id = ? WHERE id = ?", (ticket_id, email_id))
    return ticket_id


def email_document(email: dict, artist_id: int | None) -> int:
    """Store an email body as a text document so a quote in it can be underlined."""
    with db.get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO documents (owner_type, owner_id, kind, filename, path, extracted_text,
                                      received_at, email_id)
               VALUES ('artist', ?, 'other', ?, '', ?, ?, ?)""",
            (artist_id, f"email_{email['id']}.txt", email.get("body") or "", now(), email["id"]),
        )
        return int(cur.lastrowid)


def _unmatched_ticket(email: dict, ticket_type: str, summary: str) -> int:
    with db.get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO tickets (type, owner_type, owner_id, status, severity, summary, created_at, updated_at)
               VALUES (?, 'artist', NULL, 'needs_review', 'warning', ?, ?, ?)""",
            (ticket_type, summary, now(), now()),
        )
        tid = int(cur.lastrowid)
        conn.execute(
            """INSERT INTO findings (ticket_id, kind, severity, message, suggestion, quote, status)
               VALUES (?, 'low_confidence', 'warning', ?, 'Match this email to an artist by hand.', ?, 'open')""",
            (tid, f"Sender {email.get('from_addr')} does not match a known artist manager.",
             (email.get("subject") or "")[:200]),
        )
        conn.execute("UPDATE emails SET ticket_id = ? WHERE id = ?", (tid, email["id"]))
        audit(conn, tid, "system", "ticket_created", {"type": ticket_type, "unmatched": True})
    return tid


def process_rider(artist_id: int, doc_ids: list[int], *, confidence: float = 1.0) -> int:
    """Extract, match, check and file a rider. A revised rider reopens the artist's ticket."""
    items = []
    for doc_id in doc_ids:
        items += riders.extract_rider(doc_id)
    for it in items:
        it.artist_id = artist_id
    riders.match_items(items)
    riders.save_items(artist_id, items)
    found = checks.run_all(artist_id)

    if confidence < AUTO_FILE_CONFIDENCE:
        found.append(Finding(
            kind="low_confidence", severity="warning",
            message=f"The email was filed as a rider with low confidence ({confidence:.2f}).",
            suggestion="Confirm this email is a rider before acting on it.",
        ))

    with db.get_conn() as conn:
        ticket = db.row(conn.execute(
            "SELECT * FROM tickets WHERE type = 'rider_needs' AND owner_type = 'artist' AND owner_id = ?",
            (artist_id,),
        ))
        status = "needs_review" if found else "open"
        severity = max((f.severity for f in found), key=SEVERITY_RANK.get, default="info")
        summary = _summary(conn, artist_id, found, len(items))
        if ticket:
            tid = ticket["id"]
            conn.execute("DELETE FROM findings WHERE ticket_id = ?", (tid,))
            conn.execute(
                "UPDATE allocations SET status = 'released' WHERE artist_id = ? AND status = 'reserved'",
                (artist_id,),
            )
            conn.execute(
                """UPDATE tickets SET status = ?, severity = ?, summary = ?, decided_by = NULL,
                       decided_at = NULL, updated_at = ? WHERE id = ?""",
                (status, severity, summary, now(), tid),
            )
            audit(conn, tid, "system", "ticket_reopened", "Revised rider received")
        else:
            cur = conn.execute(
                """INSERT INTO tickets (type, owner_type, owner_id, status, severity, summary, created_at, updated_at)
                   VALUES ('rider_needs', 'artist', ?, ?, ?, ?, ?, ?)""",
                (artist_id, status, severity, summary, now(), now()),
            )
            tid = int(cur.lastrowid)
            audit(conn, tid, "system", "ticket_created", {"type": "rider_needs", "items": len(items)})
        for f in found:
            insert_finding(conn, tid, f)
    return tid


def _summary(conn, artist_id: int, found: list[Finding], n_items: int) -> str:
    name = conn.execute("SELECT name FROM artists WHERE id = ?", (artist_id,)).fetchone()[0]
    top = max(found, key=lambda f: SEVERITY_RANK[f.severity], default=None)
    if top is None:
        return f"{name}: rider received, {n_items} items, no problems found"
    return f"{name}: {top.message}"


def insert_finding(conn, ticket_id: int, f: Finding) -> int:
    box = riders.locate(f.doc_id, f.page, f.quote)
    cur = conn.execute(
        """INSERT INTO findings (ticket_id, kind, severity, message, suggestion, doc_id, quote, page,
                                 bbox_json, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')""",
        (ticket_id, f.kind, f.severity, f.message, f.suggestion, f.doc_id, f.quote,
         box["page"] if box else f.page, json.dumps({**box, "facts": f.facts}) if box else
         (json.dumps({"facts": f.facts}) if f.facts else None)),
    )
    return int(cur.lastrowid)


# --- approve and reject -----------------------------------------------------------------

def _ticket_artist(conn, ticket_id: int) -> tuple[dict, dict]:
    t = db.row(conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)))
    if t is None:
        raise KeyError(f"ticket {ticket_id} not found")
    a = db.row(conn.execute(
        "SELECT a.*, s.name AS stage_name FROM artists a LEFT JOIN stages s ON s.id = a.stage_id WHERE a.id = ?",
        (t["owner_id"],),
    ))
    if a is None:
        raise KeyError(f"ticket {ticket_id} has no artist")
    return t, a


def open_conflicts(ticket_id: int) -> list[dict]:
    with db.get_conn() as conn:
        return db.rows(conn.execute(
            "SELECT * FROM findings WHERE ticket_id = ? AND status = 'open' AND severity = 'conflict'",
            (ticket_id,),
        ))


def approve_rider(ticket_id: int, actor: str, override_reason: str | None = None) -> list[dict]:
    """Reserve matched technical items for the set window. Blocked by open conflicts."""
    conflicts = open_conflicts(ticket_id)
    if conflicts and not (override_reason and override_reason.strip()):
        raise RiderBlocked(f"{len(conflicts)} open conflict(s). Resolve them or give an override reason.")

    with db.get_conn() as conn:
        t, artist = _ticket_artist(conn, ticket_id)
        conn.execute("UPDATE allocations SET status = 'released' WHERE artist_id = ? AND status = 'reserved'",
                     (artist["id"],))
        items = db.rows(conn.execute(
            """SELECT r.inventory_item_id, SUM(r.quantity) AS qty, i.quantity_total FROM rider_items r
               JOIN inventory_items i ON i.id = r.inventory_item_id
               WHERE r.artist_id = ? AND r.category = 'technical' GROUP BY r.inventory_item_id""",
            (artist["id"],),
        ))
        allocations = []
        for it in items:
            taken = conn.execute(
                """SELECT COALESCE(SUM(quantity), 0) FROM allocations
                   WHERE inventory_item_id = ? AND status = 'reserved' AND start_ts < ? AND ? < end_ts""",
                (it["inventory_item_id"], artist["set_end"], artist["set_start"]),
            ).fetchone()[0]
            qty = min(it["qty"], it["quantity_total"] - taken)
            if qty <= 0:
                continue
            conn.execute(
                """INSERT INTO allocations (artist_id, inventory_item_id, quantity, start_ts, end_ts, status)
                   VALUES (?, ?, ?, ?, ?, 'reserved')""",
                (artist["id"], it["inventory_item_id"], qty, artist["set_start"], artist["set_end"]),
            )
            allocations.append({"inventory_item_id": it["inventory_item_id"], "quantity": qty})
        conn.execute("UPDATE tickets SET status = 'approved', updated_at = ? WHERE id = ?", (now(), ticket_id))
        conn.execute("UPDATE artists SET status = 'completed' WHERE id = ?", (artist["id"],))
        audit(conn, ticket_id, actor, "rider_approved",
              {"allocations": allocations, "override_reason": override_reason} if override_reason
              else {"allocations": allocations})
    notify(other_user(actor), ticket_id,
           f"{actor.title()} approved {artist['name']}'s rider. {len(allocations)} item types reserved.")
    return allocations


def reject_rider(ticket_id: int, actor: str, reason: str) -> int:
    """Draft a reason email (never sent here) and release any allocations."""
    with db.get_conn() as conn:
        t, artist = _ticket_artist(conn, ticket_id)
        conn.execute("UPDATE allocations SET status = 'released' WHERE artist_id = ? AND status = 'reserved'",
                     (artist["id"],))
        conn.execute("UPDATE tickets SET status = 'rejected', updated_at = ? WHERE id = ?", (now(), ticket_id))
        audit(conn, ticket_id, actor, "rider_rejected", {"reason": reason})
    outbox_id = emails.rider_rejection(ticket_id, artist, reason, actor)
    notify(other_user(actor), ticket_id,
           f"{actor.title()} rejected {artist['name']}'s rider. A reply to {artist['manager_name']} is drafted.")
    return outbox_id


# --- findings -------------------------------------------------------------------------

def _finding(conn, ticket_id: int, finding_id: int) -> dict:
    f = db.row(conn.execute("SELECT * FROM findings WHERE id = ? AND ticket_id = ?", (finding_id, ticket_id)))
    if f is None:
        raise KeyError(f"finding {finding_id} not on ticket {ticket_id}")
    f["facts"] = json.loads(f["bbox_json"]).get("facts", {}) if f["bbox_json"] else {}
    return f


def _refresh_status(conn, ticket_id: int) -> None:
    t = db.row(conn.execute("SELECT status FROM tickets WHERE id = ?", (ticket_id,)))
    if t["status"] in ("approved", "rejected", "resolved"):
        return
    still_open = conn.execute("SELECT COUNT(*) FROM findings WHERE ticket_id = ? AND status = 'open'",
                              (ticket_id,)).fetchone()[0]
    conn.execute("UPDATE tickets SET status = ?, updated_at = ? WHERE id = ?",
                 ("needs_review" if still_open else "in_progress", now(), ticket_id))


def resolve_finding(ticket_id: int, finding_id: int, actor: str) -> int | None:
    """Mark resolved and draft the suggested reply to the manager. Returns the outbox id."""
    with db.get_conn() as conn:
        f = _finding(conn, ticket_id, finding_id)
        _, artist = _ticket_artist(conn, ticket_id)
        conn.execute("UPDATE findings SET status = 'resolved' WHERE id = ?", (finding_id,))
        _refresh_status(conn, ticket_id)
    if f["kind"] in ("shortage", "double_booking", "over_budget"):
        return emails.finding_reply(ticket_id, artist, f, actor)
    return None


def ignore_finding(ticket_id: int, finding_id: int, actor: str) -> None:
    with db.get_conn() as conn:
        _finding(conn, ticket_id, finding_id)
        conn.execute("UPDATE findings SET status = 'ignored' WHERE id = ?", (finding_id,))
        _refresh_status(conn, ticket_id)


# --- handler for the generic /tickets router ------------------------------------------

class RiderHandler:
    def approve(self, ticket_id: int, actor: str, payload: dict | None) -> None:
        override = (payload or {}).get("override_reason")
        if open_conflicts(ticket_id) and not override:
            raise RiderBlocked("Open conflicts. Resolve them or give an override reason.")
        decide(ticket_id, actor, "approve", payload)
        approve_rider(ticket_id, actor, override)

    def reject(self, ticket_id: int, actor: str, reason: str) -> None:
        decide(ticket_id, actor, "reject", {"reason": reason})
        reject_rider(ticket_id, actor, reason)

    def resolve_finding(self, ticket_id: int, finding_id: int, actor: str) -> None:
        decide(ticket_id, actor, "resolve_finding", {"finding_id": finding_id})
        resolve_finding(ticket_id, finding_id, actor)

    def ignore_finding(self, ticket_id: int, finding_id: int, actor: str) -> None:
        decide(ticket_id, actor, "ignore_finding", {"finding_id": finding_id})
        ignore_finding(ticket_id, finding_id, actor)

    def approve_action(self, ticket_id: int, index: int, actor: str) -> None:
        raise ValueError("Rider tickets have no proposed actions.")

    def edit_action(self, ticket_id: int, index: int, actor: str, edits: dict) -> None:
        raise ValueError("Rider tickets have no proposed actions.")


register_handler("rider_needs", RiderHandler())

__all__ = ["AlreadyDecided", "RiderBlocked", "create_rider_ticket", "approve_rider", "reject_rider",
           "resolve_finding", "ignore_finding", "process_rider", "RiderHandler"]
