import json

import pytest
from fastapi.testclient import TestClient

from backend.app import db
from backend.app.main import app
from backend.app.shared import outbox


@pytest.fixture()
def client():
    db.reset()
    with TestClient(app) as c:
        yield c


def _draft(**kw):
    facts = {"subject": "Hello \u2014 there", "body": "Body \u2013 text", "context_used": ["Sparkle"], "actor": "jess"}
    facts.update(kw)
    return outbox.draft_email(None, "manager@x.example.test", "test", facts)


def test_draft_scrubs_dashes_and_adds_policy():
    db.reset()
    oid = _draft()
    with db.get_conn() as conn:
        o = db.row(conn.execute("SELECT * FROM outbox WHERE id = ?", (oid,)))
    assert o["status"] == "draft"
    assert "\u2014" not in o["subject"] and "\u2013" not in o["body"]
    assert json.loads(o["context_used_json"]) == ["Sparkle", "email_policy.md"]


def test_mock_send_marks_sent_and_refuses_twice(client, monkeypatch):
    monkeypatch.setenv("EMAIL_MODE", "mock")
    oid = _draft()
    r = client.post(f"/api/outbox/{oid}/send", headers={"X-User": "ravi"})
    assert r.status_code == 200 and r.json()["status"] == "sent" and r.json()["approved_by"] == "ravi"
    assert client.post(f"/api/outbox/{oid}/send").status_code == 400
    assert client.patch(f"/api/outbox/{oid}", json={"body": "x"}).status_code == 400


def test_patch_and_list(client):
    oid = _draft()
    r = client.patch(f"/api/outbox/{oid}", json={"subject": "New"})
    assert r.json()["subject"] == "New"
    assert any(o["id"] == oid for o in client.get("/api/outbox?status=draft").json())
    assert client.patch("/api/outbox/9999", json={"body": "x"}).status_code == 404


def test_demo_mode_delivers_only_to_demo_recipient(client, monkeypatch):
    monkeypatch.setenv("EMAIL_MODE", "demo")
    monkeypatch.setenv("DEMO_RECIPIENT", "demo@fieldday.example.test")
    delivered = []
    monkeypatch.setattr(outbox, "_smtp_deliver", lambda to, s, b: delivered.append(to))
    oid = _draft()
    assert client.post(f"/api/outbox/{oid}/send").status_code == 200
    assert delivered == ["demo@fieldday.example.test"]


def test_demo_mode_without_recipient_fails(client, monkeypatch):
    monkeypatch.setenv("EMAIL_MODE", "demo")
    monkeypatch.delenv("DEMO_RECIPIENT", raising=False)
    oid = _draft()
    assert client.post(f"/api/outbox/{oid}/send").status_code == 400
