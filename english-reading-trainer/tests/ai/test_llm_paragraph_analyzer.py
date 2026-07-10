"""Tests for app/ai/llm_paragraph_analyzer.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import app.ai.llm_paragraph_analyzer as paragraph_analyzer
from app.ai.llm_paragraph_analyzer import (
    _load_prompt,
    _render,
    _strip_frontmatter,
    analyze_paragraph_logic,
    build_paragraph_logic_prompt,
)
from app.db_connection import DatabaseConnection

MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "migrations"

VALID_PARAGRAPH_RESPONSE = json.dumps(
    {
        "paragraph_main_claim": "The policy failed because it ignored incentives.",
        "argument_flow": [
            {
                "sentence_id": 1,
                "sentence_text": "First.",
                "role": "claim",
                "reason": "It states the paragraph's main judgment.",
            }
        ],
        "evidence": ["Local behavior did not change."],
        "concession_or_counterpoint": "",
        "hidden_assumption": "Rules need incentive alignment.",
        "author_stance": "Skeptical.",
        "possible_misreading": "Treating background as the main claim.",
        "reading_check": "Find the claim before weighing evidence.",
        "takeaway_suggestion": "先找作者真正评价的那一句。",
    }
)


@pytest.fixture()
def db(tmp_path: Path) -> DatabaseConnection:
    conn = DatabaseConnection(tmp_path / "test.db")
    conn.apply_migrations(MIGRATIONS_DIR)
    return conn


def _mock_llm(return_values: list[str]):
    return patch(
        "app.ai.llm_paragraph_analyzer._call_llm",
        MagicMock(side_effect=return_values),
    )


def test_paragraph_prompt_v3_loads() -> None:
    prompt = _load_prompt("paragraph_logic_lens", "v3")

    assert "argument_flow" in prompt
    assert "Role guide" in prompt
    assert "Do not label a sentence as evidence merely" in prompt
    assert "sentence_text" in prompt
    assert "original sentence text" in prompt
    assert "{{ paragraph }}" in prompt
    assert "{{ sentence_lines }}" in prompt


def test_load_prompt_reports_missing_template(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(paragraph_analyzer, "_PROMPTS_DIR", tmp_path)

    with pytest.raises(FileNotFoundError, match="Prompt template not found"):
        _load_prompt("missing", "v1")


def test_strip_frontmatter_handles_plain_and_unclosed_text() -> None:
    assert _strip_frontmatter("plain prompt") == "plain prompt"
    assert _strip_frontmatter("---\nopen only") == "---\nopen only"


def test_build_paragraph_logic_prompt_renders_inputs() -> None:
    prompt = build_paragraph_logic_prompt(
        paragraph_text="First. Second.",
        sentence_lines="- sentence_id 1: First.",
        context="Previous paragraph: Setup.",
    )

    assert "First. Second." in prompt
    assert "- sentence_id 1: First." in prompt
    assert "Previous paragraph: Setup." in prompt


def test_render_replaces_variables() -> None:
    assert _render("{{ x }} / {{ y }}", {"x": "A", "y": "B"}) == "A / B"


def test_call_llm_returns_chat_completion_text(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeClient:
        def __init__(
            self,
            *,
            api_key: str,
            base_url: str,
            timeout: float,
            max_retries: int,
        ) -> None:
            self.api_key = api_key
            self.base_url = base_url
            assert timeout == 12.5
            assert max_retries == 2
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self.create),
            )

        def create(self, **kwargs):
            assert kwargs["model"] == "provider-model"
            assert kwargs["messages"] == [{"role": "user", "content": "Prompt"}]
            assert kwargs["temperature"] == 0.0
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="LLM reply"),
                    )
                ],
            )

    fake_openai = SimpleNamespace(OpenAI=FakeClient)
    monkeypatch.setitem(sys.modules, "openai", fake_openai)
    monkeypatch.setattr(
        paragraph_analyzer,
        "get_ai_provider_settings",
        lambda model: SimpleNamespace(
            api_key="key",
            base_url="https://example.invalid",
            model="provider-model",
            timeout_seconds=12.5,
            max_retries=2,
        ),
    )

    assert paragraph_analyzer._call_llm("Prompt", "logical-model") == "LLM reply"


def test_call_llm_wraps_provider_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenClient:
        def __init__(self, **kwargs) -> None:
            raise OSError("network down")

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=BrokenClient))

    with pytest.raises(RuntimeError, match="LLM call failed: network down"):
        paragraph_analyzer._call_llm("Prompt", "logical-model")


def test_analyze_paragraph_logic_success_and_cache(db: DatabaseConnection) -> None:
    with _mock_llm([VALID_PARAGRAPH_RESPONSE]) as mock:
        result = analyze_paragraph_logic(
            db,
            paragraph_text="First. Second.",
            sentence_lines="- sentence_id 1: First.",
            context="Previous paragraph: Setup.",
            model="test-model",
        )

    assert result.is_valid is True
    assert result.from_cache is False
    assert result.prompt_version == "paragraph_logic_lens.v4"
    assert result.model == "test-model"
    assert result.data["argument_flow"][0]["role"] == "claim"
    assert mock.call_count == 1

    with _mock_llm([]) as cached_mock:
        cached = analyze_paragraph_logic(
            db,
            paragraph_text="First. Second.",
            sentence_lines="- sentence_id 1: First.",
            context="Previous paragraph: Setup.",
            model="test-model",
        )

    assert cached.from_cache is True
    assert cached.cache_id == result.cache_id
    assert cached_mock.call_count == 0


def test_analyze_paragraph_logic_retries_invalid_response(db: DatabaseConnection) -> None:
    with _mock_llm(['{"bad": true}', VALID_PARAGRAPH_RESPONSE]):
        result = analyze_paragraph_logic(
            db,
            paragraph_text="First.",
            sentence_lines="- sentence_id 1: First.",
            model="test-model",
        )

    assert result.is_valid is True
    assert result.data["paragraph_main_claim"].startswith("The policy failed")


def test_analyze_paragraph_logic_records_invalid_after_retry(
    db: DatabaseConnection,
) -> None:
    with _mock_llm(['{"bad": true}', '{"still_bad": true}']):
        result = analyze_paragraph_logic(
            db,
            paragraph_text="First.",
            sentence_lines="- sentence_id 1: First.",
            model="test-model",
        )

    assert result.is_valid is False
    assert result.data == {}
