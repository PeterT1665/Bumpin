"""Provider-agnostic LLM client with disk caching.

Reads LLM_PROVIDER and LLM_API_KEY from .env.
Supports: openai, groq, anthropic, fake (for tests).
Caches responses to data/llm_cache/ keyed by prompt hash when LLM_CACHE=on.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import TypeVar

import fitz  # PyMuPDF
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()

T = TypeVar("T", bound=BaseModel)

_CACHE_DIR = Path(__file__).resolve().parents[3] / "data" / "llm_cache"
_PROVIDER = os.getenv("LLM_PROVIDER", "fake")
_API_KEY = os.getenv("LLM_API_KEY", "")
_CACHE_ON = os.getenv("LLM_CACHE", "off").lower() == "on"

# ---------------------------------------------------------------------------
# Fake provider (for tests and offline development)
# ---------------------------------------------------------------------------

_FAKE_RESPONSES: dict[str, str] = {}


def register_fake_response(prompt_substring: str, response_json: str) -> None:
    """Register a canned JSON response that fires when prompt contains the substring."""
    _FAKE_RESPONSES[prompt_substring] = response_json


def clear_fake_responses() -> None:
    _FAKE_RESPONSES.clear()


def _fake_complete(prompt: str) -> str:
    for substring, response in _FAKE_RESPONSES.items():
        if substring in prompt:
            return response
    return "{}"


# ---------------------------------------------------------------------------
# Real providers
# ---------------------------------------------------------------------------

def _openai_complete(prompt: str, schema: type[T]) -> str:
    import openai

    client = openai.OpenAI(api_key=_API_KEY)
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.2,
    )
    return response.choices[0].message.content or "{}"


def _groq_complete(prompt: str, schema: type[T]) -> str:
    """Groq is OpenAI-compatible. JSON mode needs the word JSON in the prompt."""
    import openai

    client = openai.OpenAI(api_key=_API_KEY, base_url="https://api.groq.com/openai/v1")
    response = client.chat.completions.create(
        model=os.getenv("LLM_MODEL", "openai/gpt-oss-120b"),
        messages=[{"role": "user", "content": prompt + "\n\nRespond with JSON only."}],
        response_format={"type": "json_object"},
        temperature=0.2,
    )
    return response.choices[0].message.content or "{}"


def _anthropic_complete(prompt: str, schema: type[T]) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=_API_KEY)
    response = client.messages.create(
        model=os.getenv("LLM_MODEL", "claude-sonnet-5-5"),
        max_tokens=4096,
        system="Respond with a single valid JSON object only. No prose, no markdown, no code fences.",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    text_block = response.content[0]
    return text_block.text if hasattr(text_block, "text") else "{}"


_PROVIDERS: dict[str, object] = {
    "openai": _openai_complete,
    "groq": _groq_complete,
    "anthropic": _anthropic_complete,
    "fake": lambda prompt, schema=None: _fake_complete(prompt),
}

# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


def _cache_key_for(prompt: str, extra: str | None = None) -> str:
    raw = prompt if extra is None else f"{extra}::{prompt}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _read_cache(key: str) -> str | None:
    if not _CACHE_ON:
        return None
    path = _CACHE_DIR / f"{key}.json"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


def _write_cache(key: str, data: str) -> None:
    if not _CACHE_ON:
        return
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR_PATH := _CACHE_DIR / f"{key}.json").write_text(data, encoding="utf-8")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class PageText(BaseModel):
    page: int
    text: str


def _strip_fences(raw: str) -> str:
    """Remove a surrounding ``` or ```json code fence, if any."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def complete_json(
    prompt: str,
    schema: type[T],
    *,
    cache_key: str | None = None,
) -> T:
    """Send a prompt to the configured LLM and return a validated pydantic model.

    If LLM_CACHE is on, responses are cached to data/llm_cache/ keyed by
    prompt hash (or the explicit cache_key).
    """
    key = cache_key or _cache_key_for(prompt)
    cached = _read_cache(key)
    if cached is not None:
        return schema.model_validate_json(cached)

    provider_fn = _PROVIDERS.get(_PROVIDER)
    if provider_fn is None:
        raise ValueError(f"Unknown LLM_PROVIDER: {_PROVIDER!r}")

    raw = provider_fn(prompt, schema)  # type: ignore[operator]

    # Parse and re-serialize to ensure valid JSON before caching
    parsed = json.loads(_strip_fences(raw))
    clean = json.dumps(parsed)
    _write_cache(key, clean)

    return schema.model_validate(parsed)


def extract_text(path: str) -> list[PageText]:
    """Extract text from a file, page by page.

    For PDFs: uses PyMuPDF text layer.
    For images: falls back to a vision LLM call.
    """
    p = Path(path)
    suffix = p.suffix.lower()

    if suffix == ".pdf":
        return _extract_pdf_text(p)
    if suffix in (".png", ".jpg", ".jpeg", ".webp", ".tiff", ".bmp"):
        return _extract_image_text(p)

    # Plain text fallback
    text = p.read_text(encoding="utf-8", errors="replace")
    return [PageText(page=1, text=text)]


def _extract_pdf_text(path: Path) -> list[PageText]:
    doc = fitz.open(str(path))
    pages: list[PageText] = []
    for i, page in enumerate(doc, start=1):
        text = page.get_text()
        if text.strip():
            pages.append(PageText(page=i, text=text))
    doc.close()

    # If no text layer found, fall back to vision
    if not pages:
        return _extract_image_text(path)
    return pages


def _extract_image_text(path: Path) -> list[PageText]:
    """Use a vision LLM to extract text from an image or image-only PDF."""
    if _PROVIDER == "fake":
        return [PageText(page=1, text=f"[fake extracted text from {path.name}]")]

    prompt = (
        "Extract all visible text from this document image. "
        "Return JSON: {\"pages\": [{\"page\": 1, \"text\": \"...\"}]}"
    )

    class _VisionResult(BaseModel):
        class _Page(BaseModel):
            page: int
            text: str
        pages: list[_Page]

    try:
        result = complete_json(
            prompt,
            _VisionResult,
            cache_key=_cache_key_for(prompt, str(path)),
        )
        return [PageText(page=p.page, text=p.text) for p in result.pages]
    except Exception:
        return [PageText(page=1, text=f"[could not extract text from {path.name}]")]
