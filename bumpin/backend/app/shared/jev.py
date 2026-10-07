"""Client for TypeSafe's Jev model ("System One"): typed questions in, typed answers out.

HTTP API: POST {base}/v1/systemone with Authorization: Bearer <key>
(docs: https://docs.typesafe.ai/api.md). One call carries three questions:
the email label (choice), the sender role (choice) and whether it is a major change (noul, 0 to 1).
"""

from __future__ import annotations

import os
import time

import httpx

from backend.app.shared import llm  # noqa: F401  (importing llm loads .env)

DEFAULT_BASE_URL = "https://api.typesafe.ai"
DEFAULT_MODEL = "jev-latest"
RETRY_STATUS = {429, 529}

LABELS = {
    "rider": "An artist or their manager sending a technical or hospitality rider: stage needs, equipment "
             "lists, dressing room and catering requests.",
    "vendor_doc": "A vendor sending compliance documents: food safety certificate, insurance, council permit "
                  "or gas certificate, or talking about when they will send one.",
    "help_or_change": "A request for help or a change: a set time moving, a cancellation, a flight problem, a "
                      "load-in time change, a stage change, or a question about logistics.",
    "unsure": "None of the above, or too vague to tell what the sender wants.",
}
ROLES = {
    "artist": "The sender is an artist or an artist's manager or agent.",
    "vendor": "The sender is a food, drink, merchandise or other stall vendor.",
    "unknown": "Cannot tell who is writing.",
}
MAJOR = ("Does this email report a major change: a set time moving, a cancellation, a stage change, an "
         "equipment quantity change, a vendor withdrawal, or a vendor load-in time change?")


def api_key() -> str:
    return os.getenv("JEV_API_KEY") or os.getenv("TYPESAFE_API_KEY") or ""


def enabled() -> bool:
    return bool(api_key())


def evaluate(state: str, *, attempts: int = 3) -> dict:
    """Call Jev once and return the parsed `answers` map. Retries 429 and 529 with backoff."""
    base = (os.getenv("JEV_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    body = {
        "model": os.getenv("JEV_MODEL") or DEFAULT_MODEL,
        "state": state,
        "questions": {
            "label": {"type": "choice", "instructions": "What kind of email is this?", "criteria": LABELS},
            "sender_role": {"type": "choice", "instructions": "Who is writing?", "criteria": ROLES},
            "is_major_change": {"type": "noul", "instructions": MAJOR},
        },
    }
    for attempt in range(attempts):
        r = httpx.post(f"{base}/v1/systemone", json=body, timeout=20,
                       headers={"Authorization": f"Bearer {api_key()}"})
        if r.status_code in RETRY_STATUS and attempt < attempts - 1:
            time.sleep(2 ** attempt)
            continue
        r.raise_for_status()
        return r.json()["answers"]
    raise RuntimeError("unreachable")
