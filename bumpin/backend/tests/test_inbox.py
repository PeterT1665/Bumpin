import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import db
from backend.app.main import app

EMAILS = Path(__file__).resolve().parents[2] / "data" / "demo" / "emails"
NOVA = {
    "from": "chris@novalane.example.test",
    "subject": "URGENT: flight cancelled",
    "body": "Hi Ravi, bad news: our flight from Sydney has been cancelled. We are rebooked and land at 9:40pm, "
            "so Nova Lane cannot make the 21:15 set. Chris",
    "attachments": [],
}


@pytest.fixture()
def client():
    db.reset()
    with TestClient(app) as c:
        yield c


def demo_email(name: str) -> dict:
    return json.loads((EMAILS / name).read_text(encoding="utf-8"))


def test_rider_email_routes_to_rider_ticket_and_saves_classification(client):
    r = client.post("/api/inbox/receive", json=demo_email("01_sparkle_rider.json")).json()
    assert r["ticket_type"] == "rider_needs" and r["ticket_status"] == "needs_review"
    t = client.get(f"/api/tickets/{r['ticket_id']}").json()
    assert t["owner"]["name"] == "Sparkle"
    assert any(f["kind"] == "shortage" and f["severity"] == "conflict" for f in t["findings"])
    with db.get_conn() as conn:
        e = db.row(conn.execute("SELECT * FROM emails WHERE id = ?", (r["email_id"],)))
        docs = db.rows(conn.execute("SELECT * FROM documents WHERE email_id = ?", (r["email_id"],)))
    assert e["classification"] == "rider" and e["confidence"] >= 0.9 and e["ticket_id"] == r["ticket_id"]
    assert len(docs) == 1 and docs[0]["extracted_text"]


def test_pasted_rider_without_attachment(client):
    r = client.post("/api/inbox/receive", json=demo_email("02_neon_tide_rider_pasted.json")).json()
    assert r["ticket_type"] == "rider_needs"
    assert any(f["kind"] == "double_booking" for f in client.get(f"/api/tickets/{r['ticket_id']}").json()["findings"])


def test_nova_flight_is_major_change_and_notifies_ravi(client):
    r = client.post("/api/inbox/receive", json=NOVA).json()
    assert r["ticket_type"] == "help" and r["notified_ravi"] is True
    t = client.get(f"/api/tickets/{r['ticket_id']}").json()
    assert t["proposed_actions"]
    notes = client.get("/api/notifications?user=ravi").json()
    assert any(n["ticket_id"] == r["ticket_id"] for n in notes)


def test_major_change_outside_window_does_not_notify(client):
    with db.get_conn() as conn:
        conn.execute("UPDATE festival SET sim_today = '2026-10-01'")
    r = client.post("/api/inbox/receive", json=NOVA).json()
    assert r["notified_ravi"] is False


def test_vague_email_lands_low_confidence_needs_review(client):
    msg = {"from": "priya@halcyon-music.example.test", "subject": "Set time",
           "body": "Could we maybe go on a bit later?", "attachments": []}
    r = client.post("/api/inbox/receive", json=msg).json()
    assert r["ticket_status"] == "needs_review" and r["confidence_band"] == "review_top"
    assert r["classification"]["confidence"] < 0.6
    t = client.get(f"/api/tickets/{r['ticket_id']}").json()
    assert t["owner"]["name"] == "Halcyon" and t["proposed_actions"] == []
    assert any(f["kind"] == "low_confidence" for f in t["findings"])


def test_unknown_sender_gibberish_gets_review_ticket(client):
    r = client.post("/api/inbox/receive", json={"from": "x@nowhere.example.test", "subject": "hi",
                                                "body": "hello there", "attachments": []}).json()
    assert r["ticket_status"] == "needs_review"
    assert r["classification"]["label"] == "unsure"


def test_missing_attachment_is_400(client):
    r = client.post("/api/inbox/receive", json={"from": "a@b.test", "subject": "s", "body": "b",
                                                "attachments": ["data/docs/nope.pdf"]})
    assert r.status_code == 400


def test_low_confidence_major_change_is_review_not_major(client, monkeypatch):
    """The live model flags the vague Halcyon email as a major change. Below 0.60 it must not alert Ravi."""
    from backend.app.shared import inbox
    from backend.app.shared.classifier import Classification

    monkeypatch.setattr(inbox, "classify", lambda text: Classification(
        label="help_or_change", confidence=0.5, reason="Vague", sender_role="artist",
        entity_hint="Halcyon", is_major_change=True))
    msg = {"from": "priya@halcyon-music.example.test", "subject": "Set time",
           "body": "Could we maybe go on a bit later?", "attachments": []}
    r = client.post("/api/inbox/receive", json=msg).json()
    assert r["is_major_change"] is False and r["notified_ravi"] is False
    assert r["confidence_band"] == "review_top"
    assert client.get("/api/notifications?user=ravi").json() == []
    card = next(c for c in client.get("/api/phone/cards?user=ravi").json() if c["ticket_id"] == r["ticket_id"])
    assert card["reason"] == "needs_review" and card["urgency"] == "high"
    with db.get_conn() as conn:
        assert conn.execute("SELECT is_major_change FROM emails WHERE id = ?", (r["email_id"],)).fetchone()[0] == 0
