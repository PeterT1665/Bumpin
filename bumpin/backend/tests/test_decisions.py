import pytest

from backend.app import db
from backend.app.shared import notifications
from backend.app.shared.decisions import AlreadyDecided, decide


@pytest.fixture(autouse=True)
def _fresh():
    db.reset()


def _ticket() -> int:
    with db.get_conn() as conn:
        return conn.execute(
            "INSERT INTO tickets (type, status, created_at, updated_at) VALUES ('help', 'open', 'x', 'x')"
        ).lastrowid


def _decided(tid):
    with db.get_conn() as conn:
        return db.row(conn.execute("SELECT decided_by, decided_at FROM tickets WHERE id = ?", (tid,)))


def test_non_final_actions_do_not_lock():
    tid = _ticket()
    for action in ("resolve_finding", "ignore_finding", "approve_action", "edit_action"):
        decide(tid, "jess", action, {"x": 1})
    assert _decided(tid)["decided_by"] is None
    decide(tid, "ravi", "approve")
    assert _decided(tid)["decided_by"] == "ravi"
    with db.get_conn() as conn:
        n = conn.execute("SELECT COUNT(*) FROM audit_log WHERE ticket_id = ?", (tid,)).fetchone()[0]
    assert n == 5


def test_second_approve_or_reject_raises():
    tid = _ticket()
    decide(tid, "ravi", "approve")
    with pytest.raises(AlreadyDecided) as e:
        decide(tid, "jess", "approve")
    assert e.value.by == "ravi" and e.value.at
    with pytest.raises(AlreadyDecided):
        decide(tid, "jess", "reject", {"reason": "no"})
    assert _decided(tid)["decided_by"] == "ravi"


def test_unknown_ticket():
    with pytest.raises(KeyError):
        decide(9999, "ravi", "approve")


def test_notifications_roundtrip():
    notifications.notify("ravi", None, "hello")
    items = notifications.list_notifications("ravi")
    assert items[0]["text"] == "hello" and items[0]["seen"] is False
    notifications.mark_seen(items[0]["id"])
    assert notifications.list_notifications("ravi", unseen_only=True) == []
