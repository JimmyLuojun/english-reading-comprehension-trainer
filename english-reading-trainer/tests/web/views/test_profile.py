"""Tests for learner profile rendering helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.web.views.profile import _latest_profile_block, _profile_save_form


@dataclass(frozen=True)
class _Snapshot:
    id: int
    created_at: datetime
    summary_md: str


def test_latest_profile_block_renders_empty_and_snapshot() -> None:
    assert _latest_profile_block(None) == '<p class="empty">No learner profile snapshots yet.</p>'

    html = _latest_profile_block(
        _Snapshot(1, datetime(2026, 6, 17), "<summary>"),
    )

    assert "Snapshot #1 from 2026-06-17" in html
    assert "&lt;summary&gt;" in html


def test_profile_save_form_posts_markdown_summary() -> None:
    html = _profile_save_form()

    assert 'action="/profile/save"' in html
    assert 'name="summary_md"' in html
