import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import db
from backend.app.main import app

EMAILS = Path(__file__).resolve().parents[2] / "data" / "demo" / "emails"
ALL = sorted(p.name for p in EMAILS.glob("0[1-8]_*.json"))


@pytest.fixture()
def client():
    db.reset()
    with TestClient(app) as c:
        yield c


def send(client, name):
    r = client.post("/api/inbox/receive", json=json.loads((EMAILS / name).read_text(encoding="utf-8")))
    assert r.status_code == 200, r.text
    return r.json()


def test_cards_empty_after_reset(client):
    assert client.get("/api/phone/cards?user=ravi").json() == []


def test_cards_shape_and_order_for_all_demo_emails(client):
    ids = {name: send(client, name)["ticket_id"] for name in ALL}
    cards = client.get("/api/phone/cards?user=ravi").json()
    assert len(cards) == len(set(ids.values()))  # the Sparkle photo reopens the Sparkle ticket
    for c in cards:
        assert {"id", "ticket_id", "urgency", "reason", "title", "summary", "snippet", "actions",
                "created_at"} <= c.keys()
        assert c["reason"] in ("major_change", "needs_review", "pending_approval")
        assert c["id"] == f"t{c['ticket_id']}"
    by_ticket = {c["ticket_id"]: c for c in cards}

    nova = by_ticket[ids["06_nova_lane_flight_cancelled.json"]]
    assert nova["reason"] == "major_change" and nova["urgency"] == "high"
    assert nova["title"] == "Nova Lane: flight cancelled" and nova["actions"] == ["approve", "edit", "dismiss"]
    assert "cancelled" in nova["snippet"]
    assert by_ticket[ids["08_harbour_coffee_load_in.json"]]["reason"] == "major_change"
    assert by_ticket[ids["07_halcyon_go_later.json"]]["reason"] == "needs_review"
    assert by_ticket[ids["07_halcyon_go_later.json"]]["urgency"] == "high"  # confidence under 0.60

    reasons = [c["reason"] for c in cards]
    first_other = next(i for i, r in enumerate(reasons) if r != "major_change")
    assert set(reasons[:first_other]) == {"major_change"} and "major_change" not in reasons[first_other:]
    urg = [c["urgency"] for c in cards]
    assert urg == sorted(urg, key=["high", "medium", "low"].index)


def test_decided_tickets_leave_the_list(client):
    tid = send(client, "08_harbour_coffee_load_in.json")["ticket_id"]
    assert any(c["ticket_id"] == tid for c in client.get("/api/phone/cards").json())
    client.post(f"/api/tickets/{tid}/approve", headers={"X-User": "ravi"})
    assert all(c["ticket_id"] != tid for c in client.get("/api/phone/cards").json())
