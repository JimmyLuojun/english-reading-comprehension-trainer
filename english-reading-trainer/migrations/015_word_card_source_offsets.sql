-- Add exact sentence offsets for word-card source locations.
--
-- Older rows identified a source only by (card, sentence, source_key), which is
-- enough for counts but not enough to highlight a specific repeated word or
-- phrase in the reader. Rebuild the table so exact occurrences can coexist.

PRAGMA foreign_keys=off;

CREATE TABLE word_card_sources_new (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id         INTEGER NOT NULL REFERENCES word_cards(id) ON DELETE CASCADE,
    sentence_id     INTEGER NOT NULL REFERENCES sentences(id) ON DELETE CASCADE,
    surface_form    TEXT    NOT NULL,
    source_key      TEXT    NOT NULL,
    start_offset    INTEGER,
    end_offset      INTEGER,
    selected_text   TEXT    NOT NULL DEFAULT '',
    is_primary      INTEGER NOT NULL DEFAULT 0 CHECK(is_primary IN (0, 1)),
    created_at      TEXT    NOT NULL,
    CHECK (
        (start_offset IS NULL AND end_offset IS NULL)
        OR (start_offset >= 0 AND end_offset > start_offset)
    )
);

INSERT INTO word_card_sources_new (
    id, card_id, sentence_id, surface_form, source_key,
    start_offset, end_offset, selected_text, is_primary, created_at
)
SELECT
    wcs.id,
    wcs.card_id,
    wcs.sentence_id,
    wcs.surface_form,
    wcs.source_key,
    CASE
        WHEN instr(lower(s.text), lower(wcs.surface_form)) > 0
         AND instr(
             substr(lower(s.text), instr(lower(s.text), lower(wcs.surface_form)) + length(wcs.surface_form)),
             lower(wcs.surface_form)
         ) = 0
        THEN instr(lower(s.text), lower(wcs.surface_form)) - 1
        ELSE NULL
    END,
    CASE
        WHEN instr(lower(s.text), lower(wcs.surface_form)) > 0
         AND instr(
             substr(lower(s.text), instr(lower(s.text), lower(wcs.surface_form)) + length(wcs.surface_form)),
             lower(wcs.surface_form)
         ) = 0
        THEN instr(lower(s.text), lower(wcs.surface_form)) - 1 + length(wcs.surface_form)
        ELSE NULL
    END,
    CASE
        WHEN instr(lower(s.text), lower(wcs.surface_form)) > 0
         AND instr(
             substr(lower(s.text), instr(lower(s.text), lower(wcs.surface_form)) + length(wcs.surface_form)),
             lower(wcs.surface_form)
         ) = 0
        THEN substr(s.text, instr(lower(s.text), lower(wcs.surface_form)), length(wcs.surface_form))
        ELSE ''
    END,
    wcs.is_primary,
    wcs.created_at
  FROM word_card_sources wcs
  JOIN sentences s ON s.id = wcs.sentence_id;

DROP TABLE word_card_sources;
ALTER TABLE word_card_sources_new RENAME TO word_card_sources;

CREATE INDEX idx_word_card_sources_card
    ON word_card_sources(card_id);

CREATE INDEX idx_word_card_sources_sentence
    ON word_card_sources(sentence_id);

CREATE UNIQUE INDEX idx_word_card_sources_one_primary
    ON word_card_sources(card_id)
    WHERE is_primary = 1;

CREATE UNIQUE INDEX idx_word_card_sources_exact_unique
    ON word_card_sources(card_id, sentence_id, source_key, start_offset, end_offset)
    WHERE start_offset IS NOT NULL AND end_offset IS NOT NULL;

CREATE UNIQUE INDEX idx_word_card_sources_legacy_unique
    ON word_card_sources(card_id, sentence_id, source_key)
    WHERE start_offset IS NULL OR end_offset IS NULL;

PRAGMA foreign_keys=on;
