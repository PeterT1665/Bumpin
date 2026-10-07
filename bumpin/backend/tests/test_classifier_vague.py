"""Vague change requests are capped to low confidence by code (planted problem 7)."""

import os

os.environ["LLM_PROVIDER"] = "fake"
os.environ["LLM_CACHE"] = "off"

import json

import pytest

from backend.app.shared.classifier import VAGUE_CONFIDENCE_CAP, classify, is_vague_change
from backend.app.shared.llm import clear_fake_responses, register_fake_response

VAGUE = ("Hey, this is Halcyon's manager. Could we maybe go on a bit later? "
         "Nothing urgent, just wondering if there's any flexibility. Cheers.")
CONCRETE = "Hi, can we move Halcyon to a later slot? We could do 10:30pm if available."
CANCELLED = "Could we maybe sort something out? Our flight has been cancelled and we are stranded."


@pytest.fixture(autouse=True)
def _reset():
    clear_fake_responses()
    yield
    clear_fake_responses()


def _confident_change(text: str) -> None:
    register_fake_response(text[:40], json.dumps({
        "label": "help_or_change", "confidence": 0.95, "reason": "Asks for a change",
        "sender_role": "artist", "entity_hint": "Halcyon", "is_major_change": True}))


def test_vague_change_is_capped_even_when_model_is_confident():
    _confident_change(VAGUE)
    result = classify(VAGUE)
    assert result.label == "help_or_change"
    assert result.confidence <= VAGUE_CONFIDENCE_CAP
    assert "needs a human" in result.reason


def test_concrete_time_is_not_capped():
    _confident_change(CONCRETE)
    assert classify(CONCRETE).confidence == pytest.approx(0.95)


def test_firm_event_is_not_capped():
    _confident_change(CANCELLED)
    assert classify(CANCELLED).confidence == pytest.approx(0.95)


def test_is_vague_change_cases():
    assert is_vague_change(VAGUE)
    assert not is_vague_change(CONCRETE)
    assert not is_vague_change(CANCELLED)
    assert not is_vague_change("Please send the site map for load-in.")
