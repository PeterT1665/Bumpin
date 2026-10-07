from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.app import artists, db
from backend.app.main import app
from backend.app.shared import registry

CLS = SimpleNamespace(confidence=0.95, entity_hint=None, is_major_change=False)


@pytest.fixture()
def client():
    db.reset()
    with TestClient(app) as c:
        yield c


def _sparkle_ticket() -> int:
    with db.get_conn() as conn:
        eid = conn.execute(
            "INSERT INTO emails (direction, from_addr, subject, body, received_at) VALUES ('in', ?, 'Rider', 'x', 'x')",
            ("sam@sparkle-mgmt.example.test",)).lastrowid
        conn.execute(
            """INSERT INTO documents (owner_type, owner_id, kind, filename, path, received_at, email_id)
               VALUES ('artist', 0, 'other', 'sparkle_rider.pdf', 'data/docs/riders/sparkle_rider.pdf', 'x', ?)""",
            (eid,))
    return artists.create_rider_ticket(eid, CLS)


def test_registry_has_artist_handlers():
    assert registry.get_handler("rider_needs") and registry.get_handler("help")
    with pytest.raises(KeyError):
        registry.get_handler("nope")


def test_detail_matches_contract_shape(client):
    tid = _sparkle_ticket()
    d = client.get(f"/api/tickets/{tid}").json()
    assert d["type"] == "rider_needs" and d["owner"]["name"] == "Sparkle"
    assert {"findings", "documents", "proposed_actions", "draft_email", "decided_by", "decided_at"} <= d.keys()
    assert any(f["kind"] == "shortage" and f["quote"] for f in d["findings"])
    assert d["documents"][0]["kind"] == "rider"
    assert d["draft_email"] is None
    assert [t["id"] for t in client.get("/api/tickets?type=rider_needs&status=needs_review").json()] == [tid]


def test_resolve_drafts_email_and_does_not_lock(client):
    tid = _sparkle_ticket()
    fid = next(f["id"] for f in client.get(f"/api/tickets/{tid}").json()["findings"] if f["kind"] == "shortage")
    d = client.post(f"/api/tickets/{tid}/findings/{fid}/resolve", headers={"X-User": "jess"}).json()
    assert d["decided_by"] is None
    assert d["draft_email"]["to"] == "sam@sparkle-mgmt.example.test"
    assert "email_policy.md" in d["draft_email"]["context_used"]


def test_blocked_approve_then_override_then_second_approve_409(client):
    tid = _sparkle_ticket()
    r = client.post(f"/api/tickets/{tid}/approve", headers={"X-User": "ravi"})
    assert r.status_code == 409 and "conflict" in r.json()["detail"].lower()
    r = client.post(f"/api/tickets/{tid}/approve", json={"override_reason": "bring own deck"},
                    headers={"X-User": "ravi"})
    assert r.status_code == 200 and r.json()["decided_by"] == "ravi" and r.json()["status"] == "approved"
    r = client.post(f"/api/tickets/{tid}/approve", json={"override_reason": "x"}, headers={"X-User": "jess"})
    assert r.status_code == 409
    assert r.json()["decided_by"] == "ravi" and r.json()["decided_at"]
    r = client.post(f"/api/tickets/{tid}/reject", json={"reason": "no"}, headers={"X-User": "jess"})
    assert r.status_code == 409


def test_error_mapping_404_and_400(client):
    assert client.get("/api/tickets/9999").status_code == 404
    assert client.post("/api/tickets/9999/approve").status_code == 404
    tid = _sparkle_ticket()
    assert client.post(f"/api/tickets/{tid}/findings/99999/ignore").status_code == 404
    r = client.post(f"/api/tickets/{tid}/actions/0/approve")
    assert r.status_code == 400
