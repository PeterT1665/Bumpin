"""Jev integration with the HTTP call mocked."""

from __future__ import annotations

import httpx
import pytest

from backend.app.shared import classifier, jev


def reply(label="help_or_change", p=0.85, conf=0.78, role="vendor", major=0.95) -> dict:
    others = {k: 0.0 for k in jev.LABELS}
    others[label] = p
    return {"model": "jev-1.13.0", "answers": {
        "label": {"type": "choice", "choice": label, "confidence": conf, "probabilities": others},
        "sender_role": {"type": "choice", "choice": role, "confidence": 0.9, "probabilities": {role: 0.9}},
        "is_major_change": {"type": "noul", "noul": major},
    }}


class FakeResponse:
    def __init__(self, status: int, payload: dict | None = None):
        self.status_code, self._payload = status, payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=None)


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv("JEV_API_KEY", "test-key")
    monkeypatch.setattr(jev.time, "sleep", lambda s: None)


def test_classify_uses_jev_label_confidence_and_major_flag(monkeypatch):
    seen = {}

    def post(url, json, timeout, headers):
        seen.update(url=url, json=json, headers=headers)
        return FakeResponse(200, reply())

    monkeypatch.setattr(jev.httpx, "post", post)
    c = classifier.classify("We need to move our load-in to 5:30am")
    assert (c.label, c.confidence, c.sender_role, c.is_major_change) == ("help_or_change", 0.78, "vendor", True)
    assert seen["url"] == "https://api.typesafe.ai/v1/systemone"
    assert seen["headers"]["Authorization"] == "Bearer test-key"
    q = seen["json"]["questions"]
    assert q["label"]["type"] == "choice" and set(q["label"]["criteria"]) == set(jev.LABELS)
    assert q["is_major_change"]["type"] == "noul" and seen["json"]["model"] == "jev-latest"


def test_retries_rate_limit_then_succeeds(monkeypatch):
    calls = iter([FakeResponse(429), FakeResponse(200, reply(label="rider", major=0.1))])
    monkeypatch.setattr(jev.httpx, "post", lambda *a, **k: next(calls))
    c = classifier.classify("Attached is our rider")
    assert c.label == "rider" and c.is_major_change is False


def test_falls_back_to_keyword_rules_when_jev_fails(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(jev.httpx, "post", boom)
    c = classifier.classify("Could we maybe go on a bit later?")
    assert c.label == "help_or_change" and c.confidence < 0.6 and "Keyword fallback" in c.reason


def test_no_key_never_calls_jev(monkeypatch):
    monkeypatch.setenv("JEV_API_KEY", "")
    monkeypatch.setattr(jev.httpx, "post", lambda *a, **k: pytest.fail("Jev was called without a key"))
    assert classifier.classify("hello there").label == "unsure"
