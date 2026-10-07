"""Tests for the LLM client module."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

os.environ["LLM_PROVIDER"] = "fake"
os.environ["LLM_CACHE"] = "off"

from pydantic import BaseModel
from backend.app.shared.llm import (
    complete_json,
    extract_text,
    register_fake_response,
    clear_fake_responses,
    PageText,
    _write_cache,
    _read_cache,
    _cache_key_for,
    _CACHE_DIR,
)


class SimpleModel(BaseModel):
    name: str
    value: int


@pytest.fixture(autouse=True)
def _reset():
    clear_fake_responses()
    yield
    clear_fake_responses()


class TestCompleteJson:
    def test_fake_provider_returns_model(self):
        register_fake_response(
            "test prompt",
            json.dumps({"name": "hello", "value": 42}),
        )
        result = complete_json("this is a test prompt", SimpleModel)
        assert isinstance(result, SimpleModel)
        assert result.name == "hello"
        assert result.value == 42

    def test_fake_provider_no_match_returns_empty(self):
        # No fake registered for this prompt, falls back to {}
        with pytest.raises(Exception):
            # {} won't validate against SimpleModel
            complete_json("unregistered prompt", SimpleModel)

    def test_unknown_provider_raises(self):
        import backend.app.shared.llm as llm_mod
        original = llm_mod._PROVIDER
        try:
            llm_mod._PROVIDER = "nonexistent"
            with pytest.raises(ValueError, match="Unknown LLM_PROVIDER"):
                complete_json("test", SimpleModel)
        finally:
            llm_mod._PROVIDER = original


class TestCacheHelpers:
    def test_cache_key_deterministic(self):
        k1 = _cache_key_for("hello")
        k2 = _cache_key_for("hello")
        assert k1 == k2

    def test_cache_key_with_extra(self):
        k1 = _cache_key_for("hello", "extra")
        k2 = _cache_key_for("hello")
        assert k1 != k2


class TestExtractText:
    def test_extract_plain_text(self, tmp_path: Path):
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("Hello world\nLine two", encoding="utf-8")
        result = extract_text(str(txt_file))
        assert len(result) == 1
        assert result[0].page == 1
        assert "Hello world" in result[0].text

    def test_extract_image_fake(self, tmp_path: Path):
        img_file = tmp_path / "test.png"
        img_file.write_bytes(b"\x89PNG fake image data")
        result = extract_text(str(img_file))
        assert len(result) == 1
        assert "fake extracted text" in result[0].text


def test_code_fences_are_stripped():
    register_fake_response("fenced", '```json\n{"name": "a", "value": 2}\n```')
    result = complete_json("fenced prompt", SimpleModel)
    assert result.name == "a" and result.value == 2
