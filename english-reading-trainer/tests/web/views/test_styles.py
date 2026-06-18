"""Tests for global CSS rendering."""

from __future__ import annotations

from app.web.views.styles import _css


def _css_block(css: str, selector: str, next_selector: str) -> str:
    start = css.index(selector)
    end = css.index(next_selector, start)
    return css[start:end]


def test_css_contains_reader_and_popover_selectors() -> None:
    css = _css()

    assert ".reader-sentence" in css
    assert ".hover-popover-panel" in css
    assert "bottom: calc(100% + 8px)" in css
    assert "right: 0" in css
    assert ".analysis-panel" in css
    assert ".analysis-section h4" in css
    assert "#sentence-panel-note-accept" in css
    assert "--analysis-panel-width: 520px" in css
    assert "@media (min-width: 1180px)" in css
    assert "padding-right: var(--analysis-panel-width)" in css
    assert "@media (max-width: 1179px)" in css
    assert ".analysis-panel-tab" in css
    assert ".analysis-open .analysis-panel-tab" in css
    assert "#toolbar-analysis-word-status" in css
    assert "[data-sentence-id].translated" in css
    assert "text-decoration-style: dotted" in css
    assert ".speak-button" in css
    assert ".word-card-delete" in css
    assert ".metric-link:hover" in css
    assert ".reader-header-actions" in css
    assert ".sentence-field-cell" in css
    assert ".sentence-field-input" in css
    assert ".sentence-field-edit[hidden]" in css
    assert "max-height: min(52vh, 360px)" in css
    assert ".similar-mistakes" in css
    assert ".similar-mistake-comparison" in css


def test_css_contains_sepia_theme_variables_and_surface_bindings() -> None:
    css = _css()

    assert 'html[data-theme="sepia"]' in css
    assert "--bg: #f3ead6" in css
    assert "--surface: #faf4e4" in css
    assert "--surface-alt: #efe3c8" in css
    assert "background: var(--nav-surface)" in css
    assert ".reader-page {\n      background: var(--surface);" in css
    assert "th { color: var(--muted); font-weight: 600; background: var(--surface-alt); }" in css
    assert "background: #f2f4f7" not in css
    assert "background: #ffffff" not in css


def test_css_visual_refresh_variables_are_mirrored_across_themes() -> None:
    css = _css()
    root_block = _css_block(css, ":root {", 'html[data-theme="sepia"]')
    sepia_block = _css_block(css, 'html[data-theme="sepia"]', "::selection")

    for variable in (
        "--text-dim:",
        "--accent-line:",
        "--accent-soft:",
        "--radius:",
        "--radius-sm:",
        "--radius-pill:",
        "--shadow:",
        "--font-display:",
    ):
        assert variable in root_block
        assert variable in sepia_block


def test_css_visual_refresh_uses_teal_accent_without_redefining_old_blue() -> None:
    css = _css()
    root_block = _css_block(css, ":root {", 'html[data-theme="sepia"]')

    assert "--accent: #0f8f83" in root_block
    assert "--accent-strong: #0c7268" in root_block
    assert "--accent: #2563eb" not in css
    assert "--accent-strong: #1d4ed8" not in css
    assert "text-decoration-color: #2563eb" in css


def test_css_visual_refresh_scopes_display_serif_to_titles() -> None:
    css = _css()

    assert 'font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;' in css
    assert "h1, h2, .reader-title {\n      font-family: var(--font-display);" in css
    assert "table {\n      width: 100%;" in css
    assert "table {\n      width: 100%;\n      font-family: var(--font-display);" not in css


def test_css_visual_refresh_followups_fill_primary_after_shared_hover() -> None:
    css = _css()
    shared_hover_selector = "nav a.active, .button.primary, button:hover, .button:hover"
    filled_primary_selector = ".button.primary, button.primary"

    assert css.index(shared_hover_selector) < css.index(filled_primary_selector)
    assert (
        ".button.primary, button.primary {\n"
        "      background: var(--accent);\n"
        "      border-color: var(--accent);\n"
        "      color: #fff;\n"
        "    }"
    ) in css
    assert (
        ".button.primary:hover, button.primary:hover {\n"
        "      background: var(--accent-strong);\n"
        "      border-color: var(--accent-strong);\n"
        "      color: #fff;\n"
        "    }"
    ) in css


def test_css_visual_refresh_followups_metric_numbers_are_tabular() -> None:
    css = _css()

    assert ".metric strong { font-size: 24px; font-variant-numeric: tabular-nums; }" in css
