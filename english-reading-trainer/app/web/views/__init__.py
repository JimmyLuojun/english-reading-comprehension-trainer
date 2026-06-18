"""Server-rendered HTML helpers for the FastAPI web interface."""

from app.web.views.layout import (
    _html_page,
    _page_header,
    _metric,
    _date,
    _active,
    _escape,
)

from app.web.views.books import (
    _books_table,
    _delete_book_form,
    _chapters_table,
    _primary_read_idx,
    _section_label,
    _strip_section_ordinal,
    _appendix_letter,
    _strip_appendix_ordinal,
)

from app.web.views.reader import (
    _reader_view,
    _reader_content_blocks,
    _reader_boundary_link,
    _group_sentence_paragraphs,
    _reader_paragraph,
    _reader_media_block,
    _word_cards_by_sentence,
    _reader_sentence_span,
    _highlight_word_cards,
    _selection_toolbar,
    _analysis_panel,
    _json_script,
)

from app.web.views.components import (
    _hover_popover,
    _source_link,
    _safe_source_href,
    _pronunciation_cell,
    _speak_button,
)

from app.web.views.cards import (
    _sentence_cards_table,
    _word_cards_table,
    _cards_return_script,
    _note_edit_cell,
    _ai_meaning_cell,
    _word_card_sources_page,
)

from app.web.views.review import (
    _due_table,
    _review_prompt_cell,
    _review_answer_cell,
)

from app.web.views.profile import (
    _latest_profile_block,
    _profile_save_form,
)

from app.web.views.imports import (
    _import_forms,
    _duplicate_page,
)
from app.web.views.styles import (
    _css,
)

from app.web.views.cards_script import (
    _def_edit_script,
)

from app.web.views.reader_script import (
    _selection_script,
)

__all__ = [
    "_active",
    "_ai_meaning_cell",
    "_analysis_panel",
    "_appendix_letter",
    "_books_table",
    "_cards_return_script",
    "_chapters_table",
    "_css",
    "_date",
    "_def_edit_script",
    "_delete_book_form",
    "_due_table",
    "_duplicate_page",
    "_escape",
    "_group_sentence_paragraphs",
    "_highlight_word_cards",
    "_hover_popover",
    "_html_page",
    "_import_forms",
    "_json_script",
    "_latest_profile_block",
    "_metric",
    "_note_edit_cell",
    "_page_header",
    "_primary_read_idx",
    "_profile_save_form",
    "_pronunciation_cell",
    "_reader_boundary_link",
    "_reader_content_blocks",
    "_reader_media_block",
    "_reader_paragraph",
    "_reader_sentence_span",
    "_reader_view",
    "_review_answer_cell",
    "_review_prompt_cell",
    "_safe_source_href",
    "_section_label",
    "_selection_script",
    "_selection_toolbar",
    "_sentence_cards_table",
    "_source_link",
    "_speak_button",
    "_strip_appendix_ordinal",
    "_strip_section_ordinal",
    "_word_cards_by_sentence",
    "_word_card_sources_page",
    "_word_cards_table",
]
