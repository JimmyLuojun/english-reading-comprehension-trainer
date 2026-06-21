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
    assert ".reader-sentence.editing-target" in css
    assert "background: rgba(96, 165, 250, 0.16)" in css
    assert "box-shadow: 0 0 0 2px rgba(96, 165, 250, 0.10)" in css
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
    assert "position: sticky;" in css
    assert "top: 0;" in css
    assert "--analysis-panel-padding: 18px" in css
    assert "--analysis-panel-padding: 16px" in css
    assert "--analysis-panel-tools-handle-width: 44px" in css
    assert ".analysis-panel.analysis-tools-collapsed:not(.analysis-tools-peeking)" in css
    assert ".analysis-panel-header:not(:hover):not(:focus-within)" in css
    assert 'content: "...";' in css
    assert "cursor: pointer;" in css
    assert "pointer-events: none;" in css
    assert "--reader-max-width: 840px" in css
    assert "max-width: var(--reader-max-width)" in css
    assert "#toolbar-analysis-word-status" in css
    assert ".toolbar-status {\n      flex: 1 0 100%;" in css
    assert "min-height: 28px;" in css
    assert "line-height: 18px;" in css
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
    assert ".analysis-input-diff" in css


def test_css_contains_sepia_theme_variables_and_surface_bindings() -> None:
    css = _css()

    assert 'html[data-theme="sepia"]' in css
    assert "--bg: #efe6d3" in css
    assert "--surface: #faf5ea" in css
    assert "--surface-alt: #f1e9d7" in css
    assert "--line: #e6dcc6" in css
    assert "--shadow: 0 16px 40px rgba(70, 55, 25, 0.07)" in css
    assert "background: var(--nav-surface)" in css
    assert ".reader-page {\n      background: var(--surface);" in css
    assert "color: var(--muted);" in css
    assert "font-size: 12px;" in css
    assert "text-transform: uppercase;" in css
    assert "background: var(--surface-alt);" in css
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


def test_css_analysis_input_diff_uses_existing_theme_tokens() -> None:
    css = _css()

    assert ".diff-added" in css
    assert ".diff-removed" in css
    assert ".diff-modified" in css
    assert ".analysis-input-diff-preview" in css
    assert ".analysis-input-diff-full-row mark.diff-mark" in css
    assert ".analysis-input-diff-full-row mark.diff-mark-removed" in css
    assert ".analysis-input-diff-full-row mark.diff-mark-added" in css
    assert "display: block;" in css
    assert "flex: 1 1 100%;" in css
    assert "min-width: 0;" in css
    assert "overflow-wrap: anywhere;" in css
    assert "grid-template-columns: auto 1fr" not in css
    assert "background: var(--accent);" in css
    assert "background: var(--danger);" in css
    assert "var(--teal)" not in css


def test_css_snapshot_inline_diff_marks_are_styled() -> None:
    css = _css()

    assert ".analysis-snapshot-text mark.diff-mark" in css
    assert ".analysis-snapshot-text mark.diff-mark-removed" in css
    assert ".analysis-snapshot-text mark.diff-mark-insert" in css


def test_css_visual_refresh_scopes_display_serif_to_titles() -> None:
    css = _css()

    assert 'font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;' in css
    assert "h1, h2, .reader-title {\n      font-family: var(--font-display);" in css
    assert "table {\n      width: 100%;" in css
    assert "table {\n      width: 100%;\n      font-family: var(--font-display);" not in css


def test_css_reader_body_type_is_larger_without_global_font_change() -> None:
    css = _css()
    reader_para = _css_block(css, ".reader-para {", ".reader-figure")

    assert "font-size: 20px;" in reader_para
    assert "line-height: 1.8;" in reader_para
    assert "font-size: 18px;" not in reader_para
    assert 'font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;' in css


def test_css_analysis_panel_body_matches_reading_size() -> None:
    css = _css()
    analysis_text = _css_block(css, ".analysis-text {", ".glossary-word {")

    # Panel body text matches the reader paragraph size (20px).
    assert "font-size: 20px;" in analysis_text


def test_css_analysis_section_labels_are_prominent_bilingual() -> None:
    css = _css()

    assert ".section-label-zh {" in css
    assert ".section-label-en {" in css
    zh = _css_block(css, ".section-label-zh {", ".analysis-section h4 .section-label-zh")
    assert "color: var(--accent-strong);" in zh
    assert "font-size: 16px;" in zh
    h3 = _css_block(css, ".analysis-section h3 {", ".analysis-section h4 {")
    assert "border-left: 4px solid var(--accent);" in h3


def test_css_word_card_lexical_type_colors_keep_sentence_yellow() -> None:
    css = _css()

    assert "[data-sentence-id].marked" in css
    assert "#ffe58a" in css
    assert '[data-word-card][data-lexical-type="word"]' in css
    assert '[data-word-card][data-lexical-type="phrase"]' in css
    assert '[data-word-card][data-lexical-type="collocation"]' in css
    assert '[data-word-card][data-lexical-type="idiom"]' in css
    assert "rgba(16, 185, 129" in css
    assert "rgba(168, 85, 247" in css
    assert "rgba(249, 115, 22" in css
    assert '.glossary-word[data-lexical-type="word"]' in css
    assert '.glossary-word[data-lexical-type="phrase"]' in css
    assert '.glossary-word[data-lexical-type="collocation"]' in css
    assert '.glossary-word[data-lexical-type="idiom"]' in css


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


def test_css_ui_consistency_width_table_and_action_density_rules() -> None:
    css = _css()

    assert "body.narrow main {\n      width: min(760px, calc(100vw - 32px));\n    }" in css
    assert "table {\n      width: 100%;" in css
    assert "box-shadow: none;" in css
    assert "tbody tr:hover { background: var(--surface-alt); }" in css
    assert "font-variant-numeric: tabular-nums;" in css
    assert ".review-item-col { width: 40%; }" in css
    assert ".answer-form {\n      gap: 6px;\n      flex-wrap: nowrap;\n    }" in css
    assert ".answer-form button { padding: 4px 10px; }" in css
    assert (
        "td button.danger, td .button.danger {\n"
        "      border-color: var(--line);\n"
        "      color: var(--muted);\n"
        "    }"
    ) in css
    assert "td button.danger:hover, td .button.danger:hover" in css
    assert ".stack-form input:not([type=file]) { max-width: 420px; }" in css
    assert ".stack-form textarea { max-width: 640px; }" in css
    assert ".stack-form button { justify-self: start; }" in css
