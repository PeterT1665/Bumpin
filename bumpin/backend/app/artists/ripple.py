"""Help tickets for artist changes, and the ripple of proposed actions (problem 6).

The AI reads the email into a Change. The new slot and who to tell are worked out
here in code. Each action only runs, and only drafts its email, when a human approves it.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from backend.app import db
from backend.app.artists import ai, emails
from backend.app.artists._compat import AlreadyDecided, audit, decide, notify, now, other_user, register_handler
from backend.app.artists.models import ProposedAction
from backend.app.artists.models import Finding
from backend.app.artists.tickets import _unmatched_ticket, email_document, find_artist, insert_finding

CHANGEOVER = timedelta(minutes=15)
REVIEW_CONFIDENCE = 0.60  # below this the request is too unclear to propose a new slot
CREW_EMAIL = "{slug}-crew@fieldday.example.test"
CATERING_EMAIL = "catering@fieldday.example.test"


def _dt(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def _hhmm(ts: str) -> str:
    return ts[11:16]


def _stage_sets(conn, stage_id: int, exclude: set[int] = frozenset()) -> list[dict]:
    return [a for a in db.rows(conn.execute(
        "SELECT * FROM artists WHERE stage_id = ? AND set_start IS NOT NULL ORDER BY set_start", (stage_id,)))
        if a["id"] not in exclude]


def _free(conn, stage_id: int, start: datetime, end: datetime, exclude: set[int]) -> bool:
    for a in _stage_sets(conn, stage_id, exclude):
        if start < _dt(a["set_end"]) + CHANGEOVER and _dt(a["set_start"]) - CHANGEOVER < end:
            return False
    return True


def ripple_for_change(artist_id: int, change: dict | ai.Change) -> list[ProposedAction]:
    """Proposed actions for a cancelled, delayed or moved set."""
    if isinstance(change, dict):
        change = ai.Change(**change)
    with db.get_conn() as conn:
        artist = db.row(conn.execute(
            "SELECT a.*, s.name AS stage_name FROM artists a JOIN stages s ON s.id = a.stage_id WHERE a.id = ?",
            (artist_id,)))
        if artist is None:
            raise KeyError(f"artist {artist_id} not found")
        start, end = _dt(artist["set_start"]), _dt(artist["set_end"])
        length = end - start
        earliest = start
        if change.earliest_start:
            h, m = map(int, change.earliest_start.split(":"))
            earliest = max(start, start.replace(hour=h, minute=m))

        later = [a for a in _stage_sets(conn, artist["stage_id"], {artist_id})
                 if _dt(a["set_start"]) >= end and _dt(a["set_start"]).date() <= start.date() + timedelta(days=1)
                 and _dt(a["set_start"]) - end < timedelta(hours=3)]
        next_act = later[0] if later else None

        actions: list[ProposedAction] = []
        if next_act:
            # Swap: the next act plays first in our slot, we follow after a changeover.
            nxt_len = _dt(next_act["set_end"]) - _dt(next_act["set_start"])
            nxt_start, nxt_end = start, start + nxt_len
            new_start = max(nxt_end + CHANGEOVER, earliest)
            new_end = new_start + length
            if not _free(conn, artist["stage_id"], new_start, new_end, {artist_id, next_act["id"]}):
                next_act = None
        if not next_act:
            new_start = max(earliest, end + CHANGEOVER) if change.kind != "time_change" else end + CHANGEOVER
            while not _free(conn, artist["stage_id"], new_start, new_start + length, {artist_id}):
                new_start += timedelta(minutes=15)
            new_end = new_start + length

        actions.append(ProposedAction(
            index=0, kind="move_set", artist_id=artist_id,
            title=f"Move {artist['name']} to {new_start:%H:%M}",
            detail=f"{artist['stage_name']}: moves from {_hhmm(artist['set_start'])} to {new_start:%H:%M}, ending {new_end:%H:%M}. "
                   f"Drafts a confirmation to {artist['manager_name']}.",
            to_addr=artist["manager_email"],
            new_start=new_start.isoformat(), new_end=new_end.isoformat(),
        ))
        changes = [f"{artist['name']}: now {new_start:%H:%M} to {new_end:%H:%M} (was {_hhmm(artist['set_start'])})"]
        if next_act:
            actions.append(ProposedAction(
                index=1, kind="move_set", artist_id=next_act["id"],
                title=f"Bring {next_act['name']} forward to {nxt_start:%H:%M}",
                detail=f"{artist['stage_name']}: moves from {_hhmm(next_act['set_start'])} to {nxt_start:%H:%M}, ending "
                       f"{nxt_end:%H:%M}. Drafts a request to {next_act['manager_name']}.",
                to_addr=next_act["manager_email"],
                new_start=nxt_start.isoformat(), new_end=nxt_end.isoformat(),
            ))
            changes.insert(0, f"{next_act['name']}: now {nxt_start:%H:%M} to {nxt_end:%H:%M} "
                              f"(was {_hhmm(next_act['set_start'])})")

        slug = artist["stage_name"].split()[0].lower()
        actions.append(ProposedAction(
            index=len(actions), kind="notify",
            title=f"Notify {artist['stage_name']} crew",
            detail="; ".join(changes), to_addr=CREW_EMAIL.format(slug=slug),
        ))
        caterers = _caterers_near(conn, artist["stage_name"])
        actions.append(ProposedAction(
            index=len(actions), kind="notify",
            title=f"Notify catering near {artist['stage_name']}",
            detail="; ".join(changes),
            to_addr=", ".join(c["contact_email"] for c in caterers) or CATERING_EMAIL,
        ))
    return actions


def _caterers_near(conn, stage_name: str) -> list[dict]:
    word = stage_name.split()[0]
    try:
        return db.rows(conn.execute(
            """SELECT name, contact_email FROM vendors WHERE type IN ('food', 'beverage')
               AND site_zone LIKE ? AND status != 'rejected' AND contact_email IS NOT NULL""",
            (f"%{word}%",)))
    except Exception:
        return []


# --- ticket creation ---------------------------------------------------------------

def create_help_ticket(email_id: int, classification) -> int:
    """Called by the inbox pipeline for 'help_or_change' from an artist."""
    with db.get_conn() as conn:
        email = db.row(conn.execute("SELECT * FROM emails WHERE id = ?", (email_id,)))
    if email is None:
        raise KeyError(f"email {email_id} not found")
    artist = find_artist(email, classification)
    if artist is None:
        return _unmatched_ticket(email, "help", "Change request received but the artist could not be identified.")

    if getattr(classification, "confidence", 1.0) < REVIEW_CONFIDENCE or getattr(classification, "label", "") == "unsure":
        return _review_ticket(email, artist, classification)

    text = f"{email.get('body') or ''}\n\nSubject: {email.get('subject') or ''}"
    change = ai.parse_change(text)
    actions = ripple_for_change(artist["id"], change)
    major = bool(getattr(classification, "is_major_change", False)) or change.kind in ("cancellation", "delay")
    first_move = actions[0]
    doc_id = email_document(email, artist["id"])
    summary = f"{artist['name']}: {change.reason.rstrip('.')}. Proposed: move to {_hhmm(first_move.new_start)}."

    with db.get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO tickets (type, owner_type, owner_id, status, severity, summary,
                                    proposed_actions_json, created_at, updated_at)
               VALUES ('help', 'artist', ?, 'needs_review', ?, ?, ?, ?, ?)""",
            (artist["id"], "conflict" if major else "warning", summary,
             json.dumps([a.model_dump() for a in actions]), now(), now()),
        )
        tid = int(cur.lastrowid)
        insert_finding(conn, tid, Finding(
            kind="schedule_change", severity="conflict" if major else "warning",
            message=f"{artist['name']} ({_hhmm(artist['set_start'])}, {_stage_name(conn, artist)}): {change.reason}",
            suggestion="Review the proposed actions below. Each one drafts its email only when approved.",
            doc_id=doc_id, quote=change.quote, page=1, facts=change.model_dump()))
        conn.execute("UPDATE emails SET ticket_id = ?, is_major_change = ? WHERE id = ?",
                     (tid, int(major), email_id))
        audit(conn, tid, "system", "ticket_created", {"type": "help", "change": change.kind})
    return tid


def _review_ticket(email: dict, artist: dict, classification) -> int:
    """Unclear request: no slot is proposed, Ravi decides what to ask the artist."""
    conf = getattr(classification, "confidence", 0.0)
    doc_id = email_document(email, artist["id"])
    quote = ai.heuristic_change(email.get("body") or "").quote or " ".join((email.get("body") or "").split())[:120]
    with db.get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO tickets (type, owner_type, owner_id, status, severity, summary, created_at, updated_at)
               VALUES ('help', 'artist', ?, 'needs_review', 'warning', ?, ?, ?)""",
            (artist["id"], f"{artist['name']}: unclear request, needs a human (confidence {conf:.2f}).",
             now(), now()),
        )
        tid = int(cur.lastrowid)
        insert_finding(conn, tid, Finding(
            kind="low_confidence", severity="warning",
            message=f"{artist['name']}'s team asked about their set, but did not say when or why. "
                    f"Bumpin is not sure what they want, so no new slot is proposed.",
            suggestion="Reply and ask for a specific time, or ignore if it is not a real request.",
            doc_id=doc_id, quote=quote, page=1))
        conn.execute("UPDATE emails SET ticket_id = ? WHERE id = ?", (tid, email["id"]))
        audit(conn, tid, "system", "ticket_created", {"type": "help", "low_confidence": conf})
    return tid


def _stage_name(conn, artist: dict) -> str:
    r = conn.execute("SELECT name FROM stages WHERE id = ?", (artist["stage_id"],)).fetchone()
    return r[0] if r else "no stage"


# --- action approval -----------------------------------------------------------------

def _load_actions(conn, ticket_id: int) -> tuple[dict, list[ProposedAction]]:
    t = db.row(conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)))
    if t is None:
        raise KeyError(f"ticket {ticket_id} not found")
    return t, [ProposedAction(**a) for a in json.loads(t["proposed_actions_json"] or "[]")]


def _save_actions(conn, ticket_id: int, actions: list[ProposedAction]) -> None:
    conn.execute("UPDATE tickets SET proposed_actions_json = ?, updated_at = ? WHERE id = ?",
                 (json.dumps([a.model_dump() for a in actions]), now(), ticket_id))


def approve_action(ticket_id: int, index: int, actor: str) -> int:
    """Apply one action and draft its email. Returns the outbox id."""
    with db.get_conn() as conn:
        t, actions = _load_actions(conn, ticket_id)
        if not 0 <= index < len(actions):
            raise KeyError(f"action {index} not on ticket {ticket_id}")
        action = actions[index]
        if action.status != "proposed":
            raise AlreadyDecided(action.approved_by, t["updated_at"])
        artist = db.row(conn.execute(
            "SELECT a.*, s.name AS stage_name FROM artists a LEFT JOIN stages s ON s.id = a.stage_id WHERE a.id = ?",
            (action.artist_id or t["owner_id"],)))
        old_start = artist["set_start"]
        if action.kind == "move_set":
            if not _free(conn, artist["stage_id"], _dt(action.new_start), _dt(action.new_end),
                         {artist["id"], *(a.artist_id for a in actions if a.kind == "move_set" and a.status == "proposed")}):
                raise ValueError("The new slot overlaps another set. Edit the time first.")
            conn.execute("UPDATE artists SET set_start = ?, set_end = ? WHERE id = ?",
                         (action.new_start, action.new_end, artist["id"]))
            conn.execute(
                "UPDATE allocations SET start_ts = ?, end_ts = ? WHERE artist_id = ? AND status = 'reserved'",
                (action.new_start, action.new_end, artist["id"]))
        audit(conn, ticket_id, actor, "action_approved", {"index": index, "title": action.title})

    if action.kind == "move_set":
        reason = ("To keep the night running after a schedule change elsewhere," if action.artist_id != t["owner_id"]
                  else "Following your message,")
        outbox_id = emails.set_change(ticket_id, artist, artist["stage_name"], _hhmm(old_start),
                                      _hhmm(action.new_start), _hhmm(action.new_end), actor, reason)
    else:
        catering = "catering" in action.title.lower()
        if catering:
            # Recipients are recomputed now, so a vendor rejected since the proposal is skipped.
            with db.get_conn() as conn:
                action.to_addr = ", ".join(c["contact_email"] for c in _caterers_near(conn, artist["stage_name"])) \
                    or CATERING_EMAIL
        outbox_id = emails.crew_notice(
            ticket_id, action.to_addr, "team" if catering else "crew", artist["stage_name"],
            action.detail.split("; "), actor, [artist["name"]],
            note="Please move artist meals and green room timing with the new sets." if catering else "")

    with db.get_conn() as conn:
        _, actions = _load_actions(conn, ticket_id)
        actions[index].status = "approved"
        actions[index].approved_by = actor
        actions[index].outbox_id = outbox_id
        _save_actions(conn, ticket_id, actions)
        if all(a.status == "approved" for a in actions):
            conn.execute("UPDATE tickets SET status = 'resolved' WHERE id = ?", (ticket_id,))
            conn.execute("UPDATE findings SET status = 'resolved' WHERE ticket_id = ? AND status = 'open'",
                         (ticket_id,))
        else:
            conn.execute("UPDATE tickets SET status = 'in_progress' WHERE id = ?", (ticket_id,))
    notify(other_user(actor), ticket_id, f"{actor.title()} approved: {action.title}. Email drafted to {action.to_addr}.")
    return outbox_id


def deny_action(ticket_id: int, index: int, actor: str) -> None:
    """Turn one proposed action down.

    The mirror of approve_action, and deliberately the quiet one: nothing moves
    on the run sheet, no reservation shifts and no email is drafted. Saying no
    to a consequence is a decision Ravi is allowed to make without it costing
    anyone a message. The ticket closes once every action has been decided
    either way, so a denied action does not leave it open forever.
    """
    with db.get_conn() as conn:
        t, actions = _load_actions(conn, ticket_id)
        if not 0 <= index < len(actions):
            raise KeyError(f"action {index} not on ticket {ticket_id}")
        action = actions[index]
        if action.status != "proposed":
            raise AlreadyDecided(action.approved_by, t["updated_at"])
        action.status = "denied"
        action.approved_by = actor
        _save_actions(conn, ticket_id, actions)
        if all(a.status != "proposed" for a in actions):
            conn.execute("UPDATE tickets SET status = 'resolved' WHERE id = ?", (ticket_id,))
            conn.execute("UPDATE findings SET status = 'resolved' WHERE ticket_id = ? AND status = 'open'",
                         (ticket_id,))
        else:
            conn.execute("UPDATE tickets SET status = 'in_progress' WHERE id = ?", (ticket_id,))
        audit(conn, ticket_id, actor, "action_denied", {"index": index, "title": action.title})
    notify(other_user(actor), ticket_id, f"{actor.title()} turned down: {action.title}.")


def edit_action(ticket_id: int, index: int, actor: str, edits: dict) -> ProposedAction:
    """Change a proposed action before approval. Accepts new_start, new_end, to_addr, detail, title."""
    allowed = {"new_start", "new_end", "to_addr", "detail", "title"}
    with db.get_conn() as conn:
        _, actions = _load_actions(conn, ticket_id)
        if not 0 <= index < len(actions):
            raise KeyError(f"action {index} not on ticket {ticket_id}")
        action = actions[index]
        if action.status == "approved":
            raise ValueError("This action is already approved.")
        for key, value in edits.items():
            if key in allowed:
                setattr(action, key, value)
        if "new_start" in edits and "new_end" not in edits and action.kind == "move_set":
            a = db.row(conn.execute("SELECT set_start, set_end FROM artists WHERE id = ?", (action.artist_id,)))
            action.new_end = (_dt(action.new_start) + (_dt(a["set_end"]) - _dt(a["set_start"]))).isoformat()
        if action.kind == "move_set" and {"new_start", "new_end"} & edits.keys() and "title" not in edits:
            action.title = action.title.rsplit(" to ", 1)[0] + f" to {_hhmm(action.new_start)}"
        _save_actions(conn, ticket_id, actions)
        audit(conn, ticket_id, actor, "action_edited", {"index": index, "edits": edits})
    return action


def _close_if_settled(conn, ticket_id: int) -> None:
    """A help ticket with nothing left open and no step still proposed is done.

    Dismissing the vague "go on a bit later?" ticket leaves no finding and no
    proposed step, and it should leave Ravi's list instead of sitting there."""
    t, actions = _load_actions(conn, ticket_id)
    still_open = conn.execute("SELECT COUNT(*) FROM findings WHERE ticket_id = ? AND status = 'open'",
                              (ticket_id,)).fetchone()[0]
    if not still_open and all(a.status != "proposed" for a in actions) and t["status"] not in ("rejected",):
        conn.execute("UPDATE tickets SET status = 'resolved', updated_at = ? WHERE id = ?", (now(), ticket_id))


class HelpHandler:
    def approve(self, ticket_id: int, actor: str, payload: dict | None) -> None:
        """Approve the whole ticket: run every remaining proposed action."""
        decide(ticket_id, actor, "approve", payload)
        with db.get_conn() as conn:
            _, actions = _load_actions(conn, ticket_id)
        for a in actions:
            if a.status == "proposed":
                approve_action(ticket_id, a.index, actor)
        with db.get_conn() as conn:
            conn.execute("UPDATE tickets SET status = 'resolved', updated_at = ? WHERE id = ?", (now(), ticket_id))

    def reject(self, ticket_id: int, actor: str, reason: str) -> None:
        decide(ticket_id, actor, "reject", {"reason": reason})
        with db.get_conn() as conn:
            conn.execute("UPDATE tickets SET status = 'rejected', updated_at = ? WHERE id = ?", (now(), ticket_id))
            audit(conn, ticket_id, actor, "help_rejected", {"reason": reason})

    def resolve_finding(self, ticket_id: int, finding_id: int, actor: str) -> None:
        decide(ticket_id, actor, "resolve_finding", {"finding_id": finding_id})
        with db.get_conn() as conn:
            conn.execute("UPDATE findings SET status = 'resolved' WHERE id = ? AND ticket_id = ?", (finding_id, ticket_id))
            _close_if_settled(conn, ticket_id)

    def ignore_finding(self, ticket_id: int, finding_id: int, actor: str) -> None:
        decide(ticket_id, actor, "ignore_finding", {"finding_id": finding_id})
        with db.get_conn() as conn:
            conn.execute("UPDATE findings SET status = 'ignored' WHERE id = ? AND ticket_id = ?", (finding_id, ticket_id))
            _close_if_settled(conn, ticket_id)

    def approve_action(self, ticket_id: int, index: int, actor: str) -> None:
        decide(ticket_id, actor, "approve_action", {"index": index})
        approve_action(ticket_id, index, actor)

    def edit_action(self, ticket_id: int, index: int, actor: str, edits: dict) -> None:
        decide(ticket_id, actor, "edit_action", {"index": index, "edits": edits})
        edit_action(ticket_id, index, actor, edits)

    def deny_action(self, ticket_id: int, index: int, actor: str) -> None:
        decide(ticket_id, actor, "deny_action", {"index": index})
        deny_action(ticket_id, index, actor)


register_handler("help", HelpHandler())
