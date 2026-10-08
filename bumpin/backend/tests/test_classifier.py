"""Tests for the classifier module.

12 fake emails covering: rider, vendor_doc, help_or_change, and ambiguous cases.
Uses the fake LLM provider so no API calls are made.
"""

from __future__ import annotations

import json
import os
import pytest

# Force fake provider before importing classifier
os.environ["LLM_PROVIDER"] = "fake"
os.environ["LLM_CACHE"] = "off"

from backend.app.shared.classifier import classify, Classification
from backend.app.shared.llm import register_fake_response, clear_fake_responses


# ---- 12 test emails ----

EMAILS = {
    # --- Rider emails (artist sending technical/hospitality needs) ---
    "rider_clear": {
        "text": (
            "Hi, I'm the manager for Sparkle. Please find attached the technical rider "
            "for the River Stage set. We need 3x CDJ-3000, 1x DJM-900, and 2x monitor "
            "wedges. Hospitality: 6x bottled water, 2x towels. Thanks, Sam."
        ),
        "expected_label": "rider",
        "expected_role": "artist",
        "expected_entity": "Sparkle",
    },
    "rider_hospitality": {
        "text": (
            "From: Marlow and The Lanes management\n"
            "Subject: Rider update\n\n"
            "Attached is the updated rider for Marlow and The Lanes. Hospitality "
            "requirements: 1x dressing room with mirror, 12x premium beers, "
            "4x bottles of sparkling water, cheese platter for 6. Technical "
            "requirements are unchanged from last email."
        ),
        "expected_label": "rider",
        "expected_role": "artist",
        "expected_entity": "Marlow and The Lanes",
    },

    # --- Vendor document emails ---
    "vendor_food_safety": {
        "text": (
            "Hi Riverside team, I'm sending through our food safety certificate "
            "for Marlow Catering. Certificate number FS-2024-1182, valid until "
            "5 December 2026. We also have our public liability insurance attached. "
            "Let me know if you need anything else. Cheers, Tom."
        ),
        "expected_label": "vendor_doc",
        "expected_role": "vendor",
        "expected_entity": "Marlow Catering",
    },
    "vendor_gas_coming": {
        "text": (
            "From: Smoke and Co\n"
            "Subject: Documents for Riverside\n\n"
            "Hey team, here's our insurance and permit for the festival. "
            "The gas certificate is coming, our inspector is booked for next week "
            "and we'll send it through as soon as we have it. Thanks, Dave."
        ),
        "expected_label": "vendor_doc",
        "expected_role": "vendor",
        "expected_entity": "Smoke and Co",
    },
    "vendor_permit": {
        "text": (
            "To whom it may concern, please find attached the council trading permit "
            "for Brew Brothers (permit #CP-4412, expires March 2027). We are a "
            "beverage vendor at Riverside. Contact: Alex, brew@example.test."
        ),
        "expected_label": "vendor_doc",
        "expected_role": "vendor",
        "expected_entity": "Brew Brothers",
    },

    # --- Help / change emails ---
    "help_flight_cancelled": {
        "text": (
            "URGENT: This is the manager for Nova Lane. Our flight from Sydney has "
            "been cancelled and we cannot make the 9:15pm set at River Stage on Saturday. "
            "Can we move to a later slot? We could do 10:30pm if available. Please advise "
            "ASAP. - Jordan"
        ),
        "expected_label": "help_or_change",
        "expected_role": "artist",
        "expected_entity": "Nova Lane",
        "expected_major": True,
    },
    "help_vendor_loadtime": {
        "text": (
            "Hi, this is Harbour Coffee Co. We need to change our load-in time from "
            "Friday 07:00 to Friday 05:30. Our truck is bigger than expected and we "
            "need extra time to set up the espresso machines. Can this be arranged? "
            "Thanks, Michelle."
        ),
        "expected_label": "help_or_change",
        "expected_role": "vendor",
        "expected_entity": "Harbour Coffee Co",
        "expected_major": True,
    },
    "help_question": {
        "text": (
            "Hi team, just a quick question. Can you confirm the power supply "
            "available at Site Zone B? We want to check whether our setup will "
            "need a generator. Thanks, River Eats."
        ),
        "expected_label": "help_or_change",
        "expected_role": "vendor",
        "expected_entity": "River Eats",
    },

    # --- Ambiguous / unsure emails ---
    "ambiguous_maybe_later": {
        "text": (
            "Hey, this is Halcyon's manager. Could we maybe go on a bit later? "
            "Nothing urgent, just wondering if there's any flexibility. Cheers."
        ),
        "expected_label": "unsure",  # or help_or_change, but vague enough to be unsure
        "expected_role": "artist",
        "expected_entity": "Halcyon",
    },
    "ambiguous_thanks": {
        "text": (
            "Thanks for the update. Looking forward to the festival! - Pat"
        ),
        "expected_label": "unsure",
        "expected_role": "unknown",
        "expected_entity": None,
    },
    "ambiguous_mixed": {
        "text": (
            "Hi, I'm from Green Grills. I have attached our food safety cert "
            "and also wanted to ask whether we can move our stall from Zone A "
            "to Zone C. We heard the foot traffic is better there."
        ),
        "expected_label": "unsure",  # mixed: vendor_doc + help_or_change
        "expected_role": "vendor",
        "expected_entity": "Green Grills",
    },
    "ambiguous_rider_or_help": {
        "text": (
            "Hi Riverside, this is Neon Tide's team. We sent the rider last week. "
            "Just checking you received it. Also, we added a keyboard player so "
            "we'll need one more DI box if possible."
        ),
        "expected_label": "unsure",  # part follow-up, part change
        "expected_role": "artist",
        "expected_entity": "Neon Tide",
    },
}


def _make_fake_response(label: str, confidence: float, reason: str,
                        sender_role: str, entity_hint: str | None,
                        is_major_change: bool = False) -> str:
    return json.dumps({
        "label": label,
        "confidence": confidence,
        "reason": reason,
        "sender_role": sender_role,
        "entity_hint": entity_hint,
        "is_major_change": is_major_change,
    })


@pytest.fixture(autouse=True)
def _reset_fake():
    clear_fake_responses()
    yield
    clear_fake_responses()


def _register_agreeing(email_key: str) -> None:
    """Register fake responses where both passes agree."""
    email = EMAILS[email_key]
    resp = _make_fake_response(
        label=email["expected_label"],
        confidence=0.92,
        reason="Test classification",
        sender_role=email["expected_role"],
        entity_hint=email.get("expected_entity"),
        is_major_change=email.get("expected_major", False),
    )
    # Both passes return same result
    register_fake_response(email["text"][:40], resp)


def _register_disagreeing(email_key: str, alt_label: str) -> None:
    """Register fake responses where passes disagree (second pass returns alt_label).

    For simplicity with the fake provider, both calls match the same substring,
    so we simulate agreement. We test disagreement logic separately.
    """
    email = EMAILS[email_key]
    resp = _make_fake_response(
        label=email["expected_label"],
        confidence=0.85,
        reason="Test classification",
        sender_role=email["expected_role"],
        entity_hint=email.get("expected_entity"),
    )
    register_fake_response(email["text"][:40], resp)


# ---- Tests: rider emails ----

class TestRiderClassification:
    def test_clear_rider(self):
        _register_agreeing("rider_clear")
        result = classify(EMAILS["rider_clear"]["text"])
        assert isinstance(result, Classification)
        assert result.label == "rider"
        assert result.sender_role == "artist"
        assert result.confidence > 0.5

    def test_hospitality_rider(self):
        _register_agreeing("rider_hospitality")
        result = classify(EMAILS["rider_hospitality"]["text"])
        assert result.label == "rider"
        assert result.sender_role == "artist"


# ---- Tests: vendor document emails ----

class TestVendorDocClassification:
    def test_food_safety_cert(self):
        _register_agreeing("vendor_food_safety")
        result = classify(EMAILS["vendor_food_safety"]["text"])
        assert result.label == "vendor_doc"
        assert result.sender_role == "vendor"
        assert result.entity_hint == "Marlow Catering"

    def test_gas_coming(self):
        _register_agreeing("vendor_gas_coming")
        result = classify(EMAILS["vendor_gas_coming"]["text"])
        assert result.label == "vendor_doc"
        assert result.sender_role == "vendor"

    def test_permit(self):
        _register_agreeing("vendor_permit")
        result = classify(EMAILS["vendor_permit"]["text"])
        assert result.label == "vendor_doc"
        assert result.sender_role == "vendor"


# ---- Tests: help / change emails ----

class TestHelpChangeClassification:
    def test_flight_cancelled(self):
        _register_agreeing("help_flight_cancelled")
        result = classify(EMAILS["help_flight_cancelled"]["text"])
        assert result.label == "help_or_change"
        assert result.is_major_change is True
        assert result.sender_role == "artist"

    def test_vendor_loadtime_change(self):
        _register_agreeing("help_vendor_loadtime")
        result = classify(EMAILS["help_vendor_loadtime"]["text"])
        assert result.label == "help_or_change"
        assert result.is_major_change is True
        assert result.sender_role == "vendor"

    def test_simple_question(self):
        _register_agreeing("help_question")
        result = classify(EMAILS["help_question"]["text"])
        assert result.label == "help_or_change"
        assert result.sender_role == "vendor"


# ---- Tests: ambiguous / unsure emails ----

class TestAmbiguousClassification:
    def test_maybe_later(self):
        """The 'Could we maybe go on a bit later?' email from the planted problems."""
        _register_agreeing("ambiguous_maybe_later")
        result = classify(EMAILS["ambiguous_maybe_later"]["text"])
        # With agreeing fake, it returns unsure
        assert result.label == "unsure"
        assert result.sender_role == "artist"

    def test_thanks_email(self):
        _register_agreeing("ambiguous_thanks")
        result = classify(EMAILS["ambiguous_thanks"]["text"])
        assert result.label == "unsure"

    def test_mixed_vendor(self):
        _register_agreeing("ambiguous_mixed")
        result = classify(EMAILS["ambiguous_mixed"]["text"])
        assert result.label == "unsure"


# ---- Tests: disagreement logic ----

class TestDisagreement:
    def test_disagreement_caps_confidence(self):
        """When both passes return different labels, confidence must be <= 0.5."""
        email = EMAILS["ambiguous_rider_or_help"]

        # Register first response for the base prompt
        resp_a = _make_fake_response(
            label="rider", confidence=0.85, reason="Looks like a rider",
            sender_role="artist", entity_hint="Neon Tide",
        )
        resp_b = _make_fake_response(
            label="help_or_change", confidence=0.70, reason="Asking for changes",
            sender_role="artist", entity_hint="Neon Tide",
        )

        # The fake provider matches by substring. We need two different responses.
        # Register the second pass prompt prefix to return the different label.
        register_fake_response("SECOND INDEPENDENT PASS", resp_b)
        register_fake_response(email["text"][:40], resp_a)

        result = classify(email["text"])
        assert result.confidence <= 0.5
        assert result.reason.startswith("Disagreement")

    def test_agreement_uses_mean_confidence(self):
        email_text = "Test email for agreement"
        resp = _make_fake_response(
            label="rider", confidence=0.90, reason="Clear rider",
            sender_role="artist", entity_hint=None,
        )
        register_fake_response("Test email", resp)
        result = classify(email_text)
        assert result.label == "rider"
        # Mean of 0.90 and 0.90 = 0.90
        assert result.confidence == pytest.approx(0.90, abs=0.01)
