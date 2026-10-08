"""A real mailbox. Polls an IMAP inbox and feeds each new email to the inbox pipeline.

Set IMAP_USER and IMAP_PASSWORD in .env (for Gmail, an App Password) and the backend
checks the inbox every IMAP_POLL_SECONDS. Each email that arrives after the app starts,
with its attachments, goes
through exactly the same path as POST /api/inbox/receive, so it is classified, routed
and turned into a ticket like any other. Nothing here sends mail.
"""

from __future__ import annotations

import email
import imaplib
import os
import re
import threading
import time
from datetime import datetime
from email import policy
from email.utils import parseaddr
from html import unescape
from pathlib import Path

from fastapi import APIRouter

from backend.app import db
from backend.app.shared import llm  # noqa: F401  (importing llm loads .env)
from backend.app.shared.inbox import InboundEmail, receive

router = APIRouter(tags=["inbox"])

INBOX_DIR = db.DATA_DIR / "inbox"
ATTACH_EXT = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".txt", ".csv"}
MAX_ATTACH_BYTES = 15 * 1024 * 1024

SEEN_SQL = "CREATE TABLE IF NOT EXISTS mailbox_seen (message_id TEXT PRIMARY KEY, email_id INTEGER, at TEXT)"

status: dict = {"enabled": False, "address": None, "last_check": None, "last_error": None,
                "processed": 0, "last_result": None}
_lock = threading.Lock()
_started = False


def _cfg() -> tuple[str, str, str, int]:
    return (os.getenv("IMAP_HOST") or "imap.gmail.com", os.getenv("IMAP_USER") or "",
            (os.getenv("IMAP_PASSWORD") or "").replace(" ", ""), int(os.getenv("IMAP_POLL_SECONDS") or 15))


def enabled() -> bool:
    _, user, password, _ = _cfg()
    return bool(user and password)


# --- one message ----------------------------------------------------------------------------

def _text_of_html(html: str) -> str:
    html = re.sub(r"(?is)<(script|style).*?</\1>", "", html)
    html = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n", html)
    return unescape(re.sub(r"<[^>]+>", "", html)).strip()


def parse(raw: bytes) -> tuple[str, str, str, str, list[tuple[str, bytes]]]:
    """(message_id, from address, subject, body text, [(filename, bytes)])."""
    msg = email.message_from_bytes(raw, policy=policy.default)
    sender = parseaddr(str(msg.get("From", "")))[1]
    subject = str(msg.get("Subject", "")).strip()
    part = msg.get_body(preferencelist=("plain", "html"))
    body = ""
    if part is not None:
        body = part.get_content()
        if part.get_content_type() == "text/html":
            body = _text_of_html(body)
    files = []
    for att in msg.iter_attachments():
        name = att.get_filename()
        if not name or Path(name).suffix.lower() not in ATTACH_EXT:
            continue
        data = att.get_payload(decode=True) or b""
        if 0 < len(data) <= MAX_ATTACH_BYTES:
            files.append((name, data))
    message_id = str(msg.get("Message-ID") or f"<{sender}|{subject}|{msg.get('Date', '')}>").strip()
    return message_id, sender, subject, body.strip(), files


def handle(raw: bytes) -> dict | None:
    """Run one raw email through the pipeline. None if it was already handled."""
    message_id, sender, subject, body, files = parse(raw)
    _, user, _, _ = _cfg()
    if sender.lower() == user.lower():
        return None  # our own outgoing copies
    with db.get_conn() as conn:
        conn.execute(SEEN_SQL)
        if conn.execute("SELECT 1 FROM mailbox_seen WHERE message_id = ?", (message_id,)).fetchone():
            return None
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    rel = []
    for name, data in files:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name).name)
        path = INBOX_DIR / f"{stamp}_{safe}"
        path.write_bytes(data)
        rel.append(str(path.relative_to(db.ROOT)))
    result = receive(InboundEmail(**{"from": sender, "subject": subject, "body": body, "attachments": rel}))
    with db.get_conn() as conn:
        conn.execute(SEEN_SQL)
        conn.execute("INSERT OR IGNORE INTO mailbox_seen (message_id, email_id, at) VALUES (?, ?, ?)",
                     (message_id, result.get("email_id"), datetime.now().isoformat(timespec="seconds")))
    return result


# --- the mailbox ----------------------------------------------------------------------------------

# Where this copy of the app started reading, per folder. Every running copy keeps
# its own, so several laptops on one mailbox each get every new email. Nothing is
# marked read in the mailbox, and a demo reset does not re-import mail already seen.
_watermarks: dict[str, int] = {}

# Spam too: repeated test emails from one address are exactly what Gmail flags, and a
# real vendor's certificate in Spam is still a certificate. A folder the provider does
# not have is skipped.
DEFAULT_FOLDERS = "INBOX,[Gmail]/Spam"


def _folders() -> list[str]:
    return [f.strip() for f in (os.getenv("IMAP_FOLDERS") or DEFAULT_FOLDERS).split(",") if f.strip()]


def _uidnext(box, folder: str) -> int:
    _, data = box.status(f'"{folder}"', "(UIDNEXT)")
    m = re.search(rb"UIDNEXT (\d+)", data[0] or b"")
    return int(m.group(1)) if m else 1


def check_once() -> list[dict]:
    """Run every email that arrived since this app started through the pipeline."""
    host, user, password, _ = _cfg()
    results = []
    with _lock:
        box = imaplib.IMAP4_SSL(host)
        try:
            box.login(user, password)
            for folder in _folders():
                typ, _ = box.select(f'"{folder}"', readonly=True)
                if typ != "OK":
                    continue
                if folder not in _watermarks:
                    _watermarks[folder] = _uidnext(box, folder) - 1  # start from now
                    continue
                mark = _watermarks[folder]
                _, data = box.uid("search", None, f"UID {mark + 1}:*")
                # "N:*" always returns the newest message, even when it is older than N.
                uids = sorted(int(u) for u in (data[0] or b"").split() if int(u) > mark)
                for uid in uids:
                    _, parts = box.uid("fetch", str(uid), "(BODY.PEEK[])")
                    raw = next((p[1] for p in parts if isinstance(p, tuple)), b"")
                    # Move past it either way, so one email that fails is not retried forever.
                    _watermarks[folder] = uid
                    r = handle(raw)
                    if r:
                        results.append(r)
        finally:
            try:
                box.logout()
            except Exception:
                pass
    status["processed"] += len(results)
    if results:
        status["last_result"] = {k: results[-1].get(k) for k in ("ticket_id", "ticket_type", "ticket_status")}
    return results


def _loop() -> None:
    while True:
        try:
            check_once()
            status["last_error"] = None
        except Exception as e:
            status["last_error"] = f"{type(e).__name__}: {e}"[:300]
        status["last_check"] = datetime.now().isoformat(timespec="seconds")
        time.sleep(_cfg()[3])


def start() -> None:
    """Called once at app start. Does nothing without IMAP credentials."""
    global _started
    status["enabled"] = enabled()
    status["address"] = _cfg()[1] or None
    if _started or not status["enabled"]:
        return
    _started = True
    threading.Thread(target=_loop, name="mailbox", daemon=True).start()


@router.get("/inbox/recent")
def recent_emails(limit: int = 10) -> list[dict]:
    """Newest incoming emails and the ticket each one opened or updated, for the
    "new email" toast on the laptop and the banner on the phone."""
    with db.get_conn() as conn:
        rows = db.rows(conn.execute(
            """SELECT e.id AS email_id, e.from_addr, e.subject, e.received_at,
                      t.id AS ticket_id, t.type AS ticket_type, t.owner_type, t.owner_id, t.summary,
                      t.created_at AS ticket_created_at,
                      COALESCE(a.name, v.name) AS owner_name,
                      (SELECT MIN(e2.id) FROM emails e2 WHERE e2.ticket_id = t.id) < e.id AS updated_existing
               FROM emails e
               LEFT JOIN tickets t ON t.id = e.ticket_id
               LEFT JOIN artists a ON t.owner_type = 'artist' AND a.id = t.owner_id
               LEFT JOIN vendors v ON t.owner_type = 'vendor' AND v.id = t.owner_id
               WHERE e.direction = 'in' AND e.ticket_id IS NOT NULL
               ORDER BY e.id DESC LIMIT ?""", (max(1, min(limit, 50)),)))
    for r in rows:
        r["updated_existing"] = bool(r["updated_existing"])
    return rows


@router.get("/inbox/mailbox")
def mailbox_status() -> dict:
    return status


@router.post("/inbox/mailbox/check")
def mailbox_check() -> dict:
    """Check now instead of waiting for the next poll."""
    if not enabled():
        return {"enabled": False, "detail": "Set IMAP_USER and IMAP_PASSWORD in .env to connect a mailbox."}
    try:
        results = check_once()
    except Exception as e:
        status["last_error"] = f"{type(e).__name__}: {e}"[:300]
        return {"enabled": True, "error": status["last_error"]}
    return {"enabled": True, "processed": len(results), "results": results}
