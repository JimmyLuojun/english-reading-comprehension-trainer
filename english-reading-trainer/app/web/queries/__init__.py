"""Database query helpers for the FastAPI web interface."""

from app.web.queries.stats import (
    _dashboard_stats,
)

from app.web.queries.books import (
    _fetch_books,
    _fetch_book,
    _delete_book,
    _fetch_reanchor_candidate_sentences,
    _find_reanchor_sentence_id,
    _find_word_reanchor_sentence_id,
    _find_phrase_reanchor_sentence_id,
    _word_card_terms,
    _phrase_card_terms,
    _word_tokens,
    _normalize_phrase_text,
    _sql_placeholders,
    _purge_book_assets_dir,
    _fetch_chapters,
    _default_read_idx,
    _fetch_chapter_by_idx,
    _fetch_adjacent_chapters,
)

from app.web.queries.reader import (
    _fetch_chapter_sentences,
    _fetch_chapter_blocks,
    _fetch_book_asset,
    _asset_storage_path,
    _fetch_active_word_cards,
)

from app.web.queries.analysis import (
    _fetch_sentence_for_analysis,
    _fetch_sentence_analysis_payload,
    _fetch_word_analysis_payload,
    _update_word_card_analysis_id,
    _fetch_cache_metadata,
    _active_sentence_prompt_version,
    _active_word_prompt_version,
)

from app.web.queries.imports import (
    _lookup_book_id_by_hash,
)

__all__ = [
    "_active_sentence_prompt_version",
    "_active_word_prompt_version",
    "_asset_storage_path",
    "_dashboard_stats",
    "_default_read_idx",
    "_delete_book",
    "_fetch_active_word_cards",
    "_fetch_book",
    "_fetch_book_asset",
    "_fetch_books",
    "_fetch_cache_metadata",
    "_fetch_chapter_blocks",
    "_fetch_chapter_by_idx",
    "_fetch_chapter_sentences",
    "_fetch_chapters",
    "_fetch_adjacent_chapters",
    "_fetch_reanchor_candidate_sentences",
    "_fetch_sentence_analysis_payload",
    "_fetch_sentence_for_analysis",
    "_fetch_word_analysis_payload",
    "_find_phrase_reanchor_sentence_id",
    "_find_reanchor_sentence_id",
    "_find_word_reanchor_sentence_id",
    "_lookup_book_id_by_hash",
    "_normalize_phrase_text",
    "_phrase_card_terms",
    "_purge_book_assets_dir",
    "_sql_placeholders",
    "_update_word_card_analysis_id",
    "_word_card_terms",
    "_word_tokens",
]
