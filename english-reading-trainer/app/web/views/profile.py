"""Learner profile rendering helpers."""

from __future__ import annotations

from typing import Any

from app.web.views.layout import _escape

def _latest_profile_block(snapshot: Any | None) -> str:
    if snapshot is None:
        return '<p class="empty">No learner profile snapshots yet.</p>'
    return f"""
    <div class="profile-summary">
      <p class="muted">Snapshot #{snapshot.id} from {snapshot.created_at.date().isoformat()}</p>
      <pre>{_escape(snapshot.summary_md)}</pre>
    </div>
    """

def _profile_save_form() -> str:
    return """
    <form method="post" action="/profile/save" class="stack-form">
      <label for="summary_md">Markdown summary</label>
      <textarea id="summary_md" name="summary_md" rows="10" placeholder="Paste the AI-generated profile Markdown here"></textarea>
      <button type="submit">Save snapshot</button>
    </form>
    """
