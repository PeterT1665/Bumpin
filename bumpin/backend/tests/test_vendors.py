"""Vendor side: seed, document parsing, eligibility, the planted problems 4 to 8 through the inbox."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import db
from backend.app.main import app
from backend.app.shared.llm import PageText
from backend.app.vendors import check_eligibility, extract_vendor_doc, recommend_rejection
from backend.app.vendors.docs import parse_pages

EMAILS = Path(__file__).resolve().parents[2] / "data" / "demo" / "emails"
DASHES = ("—", "–")


@pytest.fixture()
def client():
    db.reset()
    with TestClient(app) as c:
        yield c


def demo(client, name: str) -> dict:
    msg = json.loads((EMAILS / name).read_text(encoding="utf-8"))
    r = client.post("/api/inbox/receive", json=msg)
    assert r.status_code == 200, r.text
    return r.json()


def vendor_id(name: str) -> int:
    with db.get_conn() as conn:
        return conn.execute("SELECT id FROM vendors WHERE name = ?", (name,)).fetchone()[0]


def vendor_row(name: str) -> dict:
    with db.get_conn() as conn:
        return db.row(conn.execute("SELECT * FROM vendors WHERE name = ?", (name,)))


# --- seed -----------------------------------------------------------------------------------

def test_forty_vendors_with_zones_and_clean_generated_ones(client):
    vendors = client.get("/api/vendors").json()
    assert len(vendors) == 40
    assert all(v["site_zone"] and v["load_in_start"] and v["load_in_end"] for v in vendors)
    food_bev = [v for v in vendors if v["type"] in ("food", "beverage")]
    assert all(any(w in v["site_zone"] for w in ("River", "Lawn", "Dome")) for v in food_bev)
    clean = [v for v in vendors if v["name"] not in ("Marlow Catering", "Smoke and Co")]
    assert all(check_eligibility(v["id"]) == [] for v in clean)


def test_seed_pdfs_have_a_text_layer_and_parse():
    pages = [PageText(page=1, text="FOOD SAFETY CERTIFICATE\nIssued by: Council\nValid until: 5 December 2026\n")]
    f = parse_pages(pages)
    assert f.kind == "food_safety" and f.expiry_date == "2026-12-05" and f.quote == "Valid until: 5 December 2026"


# --- eligibility (plain code) ---------------------------------------------------------------

def test_expiry_on_festival_end_date_is_fine_but_a_day_before_is_not(client):
    vid = vendor_id("Fieldday Ice Co")
    with db.get_conn() as conn:
        conn.execute("UPDATE documents SET expiry_date = '2026-12-13' WHERE owner_id = ? AND kind = 'permit'", (vid,))
    assert check_eligibility(vid) == []
    with db.get_conn() as conn:
        conn.execute("UPDATE documents SET expiry_date = '2026-12-12' WHERE owner_id = ? AND kind = 'permit'", (vid,))
    f = check_eligibility(vid)
    assert [x.kind for x in f] == ["expired_cert"] and "12 December 2026" in f[0].message


def test_low_insurance_cover_is_flagged(client):
    vid = vendor_id("Fieldday Ice Co")
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE documents SET extracted_text = replace(extracted_text, '$20,000,000', '$1,000,000') "
            "WHERE owner_id = ? AND kind = 'insurance'", (vid,))
    f = check_eligibility(vid)
    assert len(f) == 1 and "$1,000,000" in f[0].message and "$10,000,000" in f[0].message


# --- problem 4: Marlow Catering, expired food safety certificate -----------------------------

def test_problem_4_expired_cert_recommends_rejection_with_draft(client):
    r = demo(client, "04_marlow_catering_food_safety.json")
    assert r["ticket_type"] == "vendor_eligibility" and r["ticket_status"] == "needs_review"
    t = client.get(f"/api/tickets/{r['ticket_id']}").json()
    f = next(x for x in t["findings"] if x["kind"] == "expired_cert")
    assert f["severity"] == "conflict" and "5 December 2026" in f["message"]
    assert f["quote"] == "Valid until: 5 December 2026" and f["bbox"]["rects"]  # highlight on the PDF
    d = t["draft_email"]
    assert d["to"] == "tom@marlowcatering.example.test" and d["status"] == "draft"
    assert "13 December 2026" in d["body"] and "5 December 2026" in d["body"]
    assert "email_policy.md" in d["context_used"] and "Marlow Catering" in d["context_used"]
    assert not any(x in d["subject"] + d["body"] for x in DASHES)
    assert "rejected" not in d["subject"].lower()
    assert vendor_row("Marlow Catering")["status"] == "in_progress"  # nothing decided yet


def test_reject_keeps_the_draft_and_marks_vendor_rejected_but_never_sends(client):
    tid = demo(client, "04_marlow_catering_food_safety.json")["ticket_id"]
    r = client.post(f"/api/tickets/{tid}/reject", json={"reason": "Certificate too short"},
                    headers={"X-User": "ravi"})
    assert r.status_code == 200 and r.json()["status"] == "rejected" and r.json()["decided_by"] == "ravi"
    assert vendor_row("Marlow Catering")["status"] == "rejected"
    assert all(o["status"] == "draft" for o in client.get(f"/api/outbox?ticket_id={tid}").json())
    r = client.post(f"/api/tickets/{tid}/approve", json={"override_reason": "x"}, headers={"X-User": "jess"})
    assert r.status_code == 409 and r.json()["decided_by"] == "ravi"


def test_approve_with_open_conflict_is_blocked_then_override_works(client):
    tid = demo(client, "04_marlow_catering_food_safety.json")["ticket_id"]
    r = client.post(f"/api/tickets/{tid}/approve", headers={"X-User": "ravi"})
    assert r.status_code == 409 and "decided_by" not in r.json()
    r = client.post(f"/api/tickets/{tid}/approve", json={"override_reason": "renewal in the post"},
                    headers={"X-User": "ravi"})
    assert r.status_code == 200 and vendor_row("Marlow Catering")["status"] == "completed"
    assert client.post(f"/api/tickets/{tid}/approve", headers={"X-User": "jess"}).status_code == 409


def test_resubmitting_a_good_certificate_reopens_the_same_ticket(client):
    first = demo(client, "04_marlow_catering_food_safety.json")["ticket_id"]
    client.post(f"/api/tickets/{first}/reject", json={"reason": "expired"}, headers={"X-User": "ravi"})
    assert vendor_row("Marlow Catering")["status"] == "rejected"
    resend = {"from": "tom@marlowcatering.example.test", "subject": "Updated certificate",
              "body": "Here is the renewed food safety certificate.",
              "attachments": ["data/docs/vendors/smoke_and_co_food_safety.pdf"]}
    r = client.post("/api/inbox/receive", json=resend).json()
    assert r["ticket_id"] == first and r["ticket_status"] == "open"
    t = client.get(f"/api/tickets/{first}").json()
    assert t["findings"] == [] and t["decided_by"] is None
    assert vendor_row("Marlow Catering")["status"] == "in_progress"
    assert client.post(f"/api/tickets/{first}/approve", headers={"X-User": "jess"}).status_code == 200
    assert vendor_row("Marlow Catering")["status"] == "completed"


def test_recommend_rejection_needs_an_open_conflict(client):
    demo(client, "04_marlow_catering_food_safety.json")
    vid = vendor_id("Marlow Catering")
    assert recommend_rejection(vid) > 0
    with db.get_conn() as conn:
        conn.execute("UPDATE findings SET status = 'resolved'")
    with pytest.raises(ValueError):
        recommend_rejection(vid)


# --- problem 5: Smoke and Co, gas certificate "coming" ---------------------------------------

def test_problem_5_missing_gas_certificate(client):
    r = demo(client, "05_smoke_and_co_gas_coming.json")
    assert r["ticket_type"] == "vendor_eligibility" and r["ticket_status"] == "needs_review"
    t = client.get(f"/api/tickets/{r['ticket_id']}").json()
    assert [f["kind"] for f in t["findings"]] == ["missing_doc"]
    assert t["findings"][0]["severity"] == "conflict" and '"coming"' in t["findings"][0]["message"]
    assert "gas" in t["draft_email"]["body"].lower()


# --- problem 8: Harbour Coffee Co, load-in moves earlier -------------------------------------

def test_problem_8_load_in_changes_only_after_a_human_approves(client):
    r = demo(client, "08_harbour_coffee_load_in.json")
    assert r["is_major_change"] is True and r["notified_ravi"] is True
    assert vendor_row("Harbour Coffee Co")["load_in_start"] == "2026-12-11T07:00:00"
    t = client.get(f"/api/tickets/{r['ticket_id']}").json()
    assert t["findings"][0]["kind"] == "schedule_change"
    action = t["proposed_actions"][0]
    assert action["new_start"] == "2026-12-11T05:30:00" and action["status"] == "proposed"
    assert any(n["ticket_id"] == r["ticket_id"] for n in client.get("/api/notifications?user=ravi").json())

    done = client.post(f"/api/tickets/{r['ticket_id']}/actions/0/approve", headers={"X-User": "ravi"}).json()
    assert done["status"] == "resolved" and done["decided_by"] is None
    v = vendor_row("Harbour Coffee Co")
    assert v["load_in_start"] == "2026-12-11T05:30:00" and v["load_in_end"] == "2026-12-11T07:30:00"
    d = done["draft_email"]
    assert d["to"] == "dana@harbourcoffee.example.test" and "05:30" in d["body"]
    assert client.post(f"/api/tickets/{r['ticket_id']}/actions/0/approve").status_code == 409
    notes = client.get("/api/notifications?user=jess").json()
    assert any("approved" in n["text"] for n in notes)


def test_edit_action_then_approve_applies_the_edit(client):
    tid = demo(client, "08_harbour_coffee_load_in.json")["ticket_id"]
    t = client.post(f"/api/tickets/{tid}/actions/0/edit", json={"new_start": "2026-12-11T06:00:00"}).json()
    assert t["proposed_actions"][0]["new_end"] == "2026-12-11T08:00:00"
    client.post(f"/api/tickets/{tid}/approve", headers={"X-User": "jess"})
    assert vendor_row("Harbour Coffee Co")["load_in_start"] == "2026-12-11T06:00:00"


def test_vendor_change_outside_the_window_does_not_notify_immediately(client):
    with db.get_conn() as conn:
        conn.execute("UPDATE festival SET sim_today = '2026-10-01'")
    assert demo(client, "08_harbour_coffee_load_in.json")["notified_ravi"] is False


def test_document_ticket_has_no_actions(client):
    tid = demo(client, "04_marlow_catering_food_safety.json")["ticket_id"]
    assert client.post(f"/api/tickets/{tid}/actions/0/approve").status_code == 400
    assert client.post(f"/api/tickets/{tid}/actions/0/edit", json={}).status_code == 400


# --- problems 6 and 7 through the same pipeline ---------------------------------------------

def test_problem_6_nova_lane_flight_cancelled(client):
    r = demo(client, "06_nova_lane_flight_cancelled.json")
    assert r["ticket_type"] == "help" and r["notified_ravi"] is True and r["is_major_change"] is True
    t = client.get(f"/api/tickets/{r['ticket_id']}").json()
    assert t["owner"]["name"] == "Nova Lane" and t["findings"][0]["kind"] == "schedule_change"
    moves = [a for a in t["proposed_actions"] if a["kind"] == "move_set"]
    assert any(a["new_start"].endswith("T22:45:00") for a in moves)
    assert any(a["kind"] == "notify" for a in t["proposed_actions"])


def test_problem_7_vague_halcyon_email_needs_review(client):
    r = demo(client, "07_halcyon_go_later.json")
    assert r["ticket_status"] == "needs_review" and r["confidence_band"] == "review_top"
    assert r["classification"]["confidence"] < 0.6 and r["notified_ravi"] is False
    t = client.get(f"/api/tickets/{r['ticket_id']}").json()
    assert t["owner"]["name"] == "Halcyon" and t["proposed_actions"] == []


# --- extract_vendor_doc ---------------------------------------------------------------------

def test_extract_vendor_doc_saves_facts_on_the_row(client):
    with db.get_conn() as conn:
        doc = db.row(conn.execute("SELECT * FROM documents WHERE owner_type = 'vendor' AND kind = 'permit' LIMIT 1"))
        conn.execute("UPDATE documents SET expiry_date = NULL, issuer = NULL WHERE id = ?", (doc["id"],))
    facts = extract_vendor_doc(doc["id"])
    assert facts.kind == "permit" and facts.expiry_date == doc["expiry_date"] and facts.page == 1
    with db.get_conn() as conn:
        again = db.row(conn.execute("SELECT * FROM documents WHERE id = ?", (doc["id"],)))
    assert again["expiry_date"] == doc["expiry_date"] and again["issuer"]
