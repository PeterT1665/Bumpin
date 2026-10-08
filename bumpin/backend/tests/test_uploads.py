"""Upload screen: equipment lists become inventory rows, everything else becomes memory."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.app import db
from backend.app.artists import ai, emails, routes, tickets, uploads  # noqa: F401  (routes registers the reset hook)
from backend.app.main import app

MANIFEST = (
    "Stage,Item,Category,Quantity,Also known as\n"
    "River Stage,Pioneer CDJ-3000,dj,2,CDJ-3000; CDJ 3000\n"
    "River Stage,Fog machine,fx,3,fogger; smoke machine\n"
)
POLICY = ("Item,Unit cost AUD,Also known as\n"
          "Private dressing room,350,dressing room\n"
          "Bottle of champagne,140,champagne\n")


@pytest.fixture(autouse=True)
def fresh_db():
    db.reset()


def post(client, *files):
    return client.post("/api/uploads", files=[("files", (n, d.encode(), "text/csv")) for n, d in files]).json()


def inventory(name: str, stage_id: int | None = 1) -> dict | None:
    with db.get_conn() as conn:
        return db.row(conn.execute(
            "SELECT * FROM inventory_items WHERE canonical_name = ? AND stage_id IS ?", (name, stage_id)))


def test_equipment_csv_becomes_inventory_rows():
    with TestClient(app) as client:
        r = post(client, ("riverside_equipment_manifest.csv", MANIFEST))[0]
    assert r["kind"] == "equipment" and r["stored_as"] == "equipment" and r["decided_by"] == "code"
    assert r["equipment"]["added"] == 1 and r["equipment"]["unchanged"] == 1
    fog = inventory("Fog machine")
    assert fog["quantity_total"] == 3 and "fogger" in fog["aliases_json"]


def test_changed_quantity_reruns_rider_checks():
    eid = None
    with db.get_conn() as conn:
        eid = conn.execute(
            "INSERT INTO emails (direction, from_addr, subject, body, received_at) VALUES ('in', ?, 'Rider', 'x', 'x')",
            ("sam@sparkle-mgmt.example.test",)).lastrowid
        conn.execute("""INSERT INTO documents (owner_type, owner_id, kind, filename, path, received_at, email_id)
                        VALUES ('artist', 0, 'other', 's.pdf', 'data/docs/riders/sparkle_rider.pdf', 'x', ?)""", (eid,))
    tid = tickets.create_rider_ticket(eid, SimpleNamespace(confidence=0.95, entity_hint=None, is_major_change=False))
    with TestClient(app) as client:
        r = post(client, ("equipment.csv", "Stage,Item,Quantity\nRiver Stage,Pioneer CDJ-3000,1\n"))[0]
    assert r["equipment"]["updated"] == 1 and r["riders_rechecked"] >= 1
    with db.get_conn() as conn:
        msgs = [f["message"] for f in db.rows(conn.execute(
            "SELECT message FROM findings WHERE ticket_id = ? AND kind = 'shortage'", (tid,)))]
    assert any("River Stage has 1" in m for m in msgs)


def test_rerun_keeps_decisions_and_reservations():
    with db.get_conn() as conn:
        before = db.row(conn.execute("SELECT status, decided_by FROM tickets WHERE owner_id = 2"))
        reserved = conn.execute("SELECT COUNT(*) FROM allocations WHERE status = 'reserved'").fetchone()[0]
    with TestClient(app) as client:
        post(client, ("equipment.csv", "Stage,Item,Quantity\nRiver Stage,Pioneer CDJ-3000,5\n"))
    with db.get_conn() as conn:
        after = db.row(conn.execute("SELECT status, decided_by FROM tickets WHERE owner_id = 2"))
        assert conn.execute("SELECT COUNT(*) FROM allocations WHERE status = 'reserved'").fetchone()[0] == reserved
    assert before == after == {"status": "approved", "decided_by": "jess"}


def test_priced_list_and_brief_become_memory():
    with TestClient(app) as client:
        res = post(client, ("riverside_hospitality_policy.csv", POLICY),
                   ("riverside_festival_brief.csv", "Field,Value\nFestival,Riverside\nLast day,2026-12-13\n"))
        mem = client.get("/api/memory").json()
    assert [r["stored_as"] for r in res] == ["memory", "memory"]
    assert [r["kind"] for r in res] == ["policy", "festival_brief"]
    assert {m["filename"] for m in mem} == {"riverside_hospitality_policy.csv", "riverside_festival_brief.csv"}
    notes, names = uploads.memory_context()
    assert "Private dressing room" in notes and names[0] == "riverside_festival_brief.csv"


def test_pdf_upload_is_read():
    data = open(db.ROOT / "data/docs/riders/halcyon_rider.pdf", "rb").read()
    with TestClient(app) as client:
        r = client.post("/api/uploads", files=[("files", ("halcyon_rider.pdf", data, "application/pdf"))]).json()[0]
    assert r["stored_as"] == "memory" and r["kind"] == "rider"
    with db.get_conn() as conn:
        text = conn.execute("SELECT text FROM memory WHERE id = ?", (r["memory_id"],)).fetchone()[0]
    assert "Moog One" in text


def test_email_polish_keeps_facts_and_lists_memory(monkeypatch):
    uploads.remember("riverside_hospitality_policy.csv", db.ROOT / "README.md", "policy", POLICY, "Prices")
    monkeypatch.setattr(ai, "llm_enabled", lambda: True)
    body = "Hi Sam,\n\nYour rider lists 3x Pioneer CDJ-3000, and River Stage has 2.\n\nKind regards"

    monkeypatch.setattr(emails.llm, "complete_json", lambda prompt, schema: schema(
        subject="Your rider", body="Hi Sam,\n\nThanks for the rider. We can do 3 decks.\n\nKind regards"))
    assert emails.polish("Your rider", body) == ("Your rider", body, [])  # dropped "2": rejected

    monkeypatch.setattr(emails.llm, "complete_json", lambda prompt, schema: schema(
        subject="Your rider", body="Hi Sam,\n\nYou asked for 3x Pioneer CDJ-3000 and River Stage has 2.\n\nKind regards"))
    s, b, read = emails.polish("Your rider", body)
    assert "You asked for" in b and read == ["riverside_hospitality_policy.csv"]


def test_unreadable_file_does_not_break_the_batch():
    with TestClient(app) as client:
        res = post(client, ("notes.txt", "Load-in gate opens at 05:00."), ("empty.csv", ""))
    assert [r["stored_as"] for r in res] == ["memory", "memory"]
