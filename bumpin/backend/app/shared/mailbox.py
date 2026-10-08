"""A real mailbox. Polls an IMAP inbox and feeds each new email to the inbox pipeline.

Set IMAP_USER and IMAP_PASSWORD in .env (for Gmail, an App Password) and the backend
checks the inbox every IMAP_POLL_SECONDS. Each new email, with its attachments, goes
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

def check_once() -> list[dict]:
    """Fetch every unread email, run each through the pipeline, mark it read."""
    host, user, password, _ = _cfg()
    results = []
    with _lock:
        box = imaplib.IMAP4_SSL(host)
        try:
            box.login(user, password)
            box.select("INBOX")
            _, data = box.search(None, "UNSEEN")
            for num in (data[0] or b"").split():
                _, parts = box.fetch(num, "(BODY.PEEK[])")
                raw = next((p[1] for p in parts if isinstance(p, tuple)), b"")
                try:
                    r = handle(raw)
                    if r:
                        results.append(r)
                finally:
                    # Read either way, so one email that fails is not retried forever.
                    box.store(num, "+FLAGS", "\\Seen")
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
