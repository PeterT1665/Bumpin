"""Real mailbox: emails from addresses BumpIn does not know, with attachments, become tickets."""

from __future__ import annotations

import json
from email.message import EmailMessage

import pytest

from backend.app import db
from backend.app.artists import routes  # noqa: F401  (registers the reset hook)
from backend.app.shared import inbox, mailbox
from backend.app.shared.classifier import Classification


@pytest.fixture(autouse=True)
def fresh_db(monkeypatch):
    db.reset()
    monkeypatch.setenv("IMAP_USER", "bumpin.demo@example.test")
    monkeypatch.setenv("IMAP_PASSWORD", "x")


def raw_email(sender, subject, body, attachment=None, html=False, message_id=None):
    m = EmailMessage()
    m["From"] = sender
    m["To"] = "bumpin.demo@example.test"
    m["Subject"] = subject
    m["Message-ID"] = message_id or f"<{subject.replace(' ', '')}@test>"
    if html:
        m.set_content(body.replace("<p>", "").replace("</p>", "\n"))
        m.add_alternative(body, subtype="html")
    else:
        m.set_content(body)
    if attachment:
        name, data, maintype, subtype = attachment
        m.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    return m.as_bytes()


def fixed_class(monkeypatch, label, hint=None, major=False, conf=0.95):
    monkeypatch.setattr(inbox, "classify", lambda text: Classification(
        label=label, confidence=conf, reason="test", sender_role="unknown", entity_hint=hint,
        is_major_change=major))


def ticket(tid):
    with db.get_conn() as conn:
        return db.row(conn.execute("SELECT * FROM tickets WHERE id = ?", (tid,)))


def test_rider_with_pdf_from_unknown_address(monkeypatch):
    fixed_class(monkeypatch, "rider")  # no name from the model: found in the subject instead
    pdf = open(db.ROOT / "data/docs/riders/sparkle_rider.pdf", "rb").read()
    r = mailbox.handle(raw_email("Peter <peter.personal@gmail.com>", "Sparkle rider for Riverside",
                                 "Hi, rider attached.", ("sparkle_rider.pdf", pdf, "application", "pdf")))
    t = ticket(r["ticket_id"])
    assert r["ticket_type"] == "rider_needs" and t["owner_id"] == 1
    with db.get_conn() as conn:
        doc = db.row(conn.execute("SELECT * FROM documents WHERE email_id = ?", (r["email_id"],)))
        kinds = [f["kind"] for f in db.rows(conn.execute("SELECT kind FROM findings WHERE ticket_id = ?", (t["id"],)))]
    assert doc["path"].startswith("data/inbox/") and doc["path"].endswith("sparkle_rider.pdf")
    assert "shortage" in kinds


def test_same_email_twice_is_handled_once(monkeypatch):
    fixed_class(monkeypatch, "rider", hint="Sparkle")
    raw = raw_email("peter.personal@gmail.com", "Sparkle rider", "1x Shure SM58")
    assert mailbox.handle(raw) is not None
    assert mailbox.handle(raw) is None


def test_schedule_change_from_unknown_address_gets_proposed_actions(monkeypatch):
    fixed_class(monkeypatch, "help_or_change", major=True)
    r = mailbox.handle(raw_email(
        "someone@gmail.com", "Flight cancelled",
        "Hi Ravi, Nova Lane's flight from Sydney has been cancelled. We land at 9:40pm."))
    t = ticket(r["ticket_id"])
    assert r["ticket_type"] == "help" and t["owner_id"] == 5
    assert len(json.loads(t["proposed_actions_json"])) == 4


def test_vendor_matched_by_longest_name(monkeypatch):
    role, who = inbox.sender_by_name(None, "Sending through the Marlow Catering certificate")
    assert role == "vendor" and who["name"] == "Marlow Catering"
    role, who = inbox.sender_by_name(None, "Marlow & The Lanes updated rider")
    assert role == "artist" and who["name"] == "Marlow & The Lanes"
    assert inbox.sender_by_name(None, "Hello, is anyone there?") == ("unknown", None)


def test_unknown_artist_goes_to_review(monkeypatch):
    fixed_class(monkeypatch, "rider")
    r = mailbox.handle(raw_email("new@gmail.com", "Our rider", "Rider for an act you have never heard of."))
    assert ticket(r["ticket_id"])["status"] == "needs_review"


def test_html_only_body_is_read(monkeypatch):
    fixed_class(monkeypatch, "rider", hint="Sparkle")
    _, sender, subject, body, files = mailbox.parse(raw_email(
        "a@b.test", "Sparkle", "<p>Hi team</p><p>2x Shure SM58</p>", html=True))
    assert "2x Shure SM58" in body and files == []


def test_own_outgoing_copy_is_ignored():
    assert mailbox.handle(raw_email("bumpin.demo@example.test", "Re: rider", "sent by us")) is None


def test_every_running_copy_gets_new_mail_and_nothing_is_marked_read(monkeypatch):
    fixed_class(monkeypatch, "rider", hint="Sparkle")
    raw = raw_email("peter@gmail.com", "Sparkle rider", "1x Shure SM58")
    calls = []

    class FakeIMAP:
        uidnext = 50
        def __init__(self, host): calls.append(("connect", host))
        def login(self, u, p): calls.append(("login", u))
        def select(self, box, readonly=False): calls.append(("select", box, readonly))
        def status(self, box, what): return "OK", [f"INBOX (UIDNEXT {FakeIMAP.uidnext})".encode()]
        def uid(self, cmd, *args):
            calls.append(("uid", cmd) + args)
            if cmd == "search":  # "50:*" on a box whose newest is 49 still returns 49
                return "OK", [b"49 50" if FakeIMAP.uidnext > 50 else b"49"]
            return "OK", [(b"50 (BODY[] {n}", raw), b")"]
        def store(self, *a): calls.append(("store",) + a)
        def logout(self): calls.append(("logout",))

    monkeypatch.setattr(mailbox.imaplib, "IMAP4_SSL", FakeIMAP)
    monkeypatch.setattr(mailbox, "_watermark", None)
    assert mailbox.check_once() == []          # first check only notes where the inbox is
    assert mailbox.check_once() == []          # nothing new: the old message 49 is skipped
    FakeIMAP.uidnext = 51                       # message 50 arrives
    results = mailbox.check_once()
    assert len(results) == 1 and results[0]["ticket_type"] == "rider_needs"
    assert not [c for c in calls if c[0] == "store"]
    assert ("select", "INBOX", True) in calls

    # A second laptop on the same mailbox, started before message 50, files it too.
    db.reset()
    monkeypatch.setattr(mailbox, "_watermark", 49)
    assert len(mailbox.check_once()) == 1
