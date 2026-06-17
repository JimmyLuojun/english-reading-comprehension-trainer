-- Track distinct source locations for word cards.
--
-- occurrence_count now means the number of distinct recorded source locations,
-- not the number of times the Mark action was clicked.

CREATE TABLE IF NOT EXISTS word_card_sources (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id         INTEGER NOT NULL REFERENCES word_cards(id) ON DELETE CASCADE,
    sentence_id     INTEGER NOT NULL REFERENCES sentences(id) ON DELETE CASCADE,
    surface_form    TEXT    NOT NULL,
    source_key      TEXT    NOT NULL,
    is_primary      INTEGER NOT NULL DEFAULT 0 CHECK(is_primary IN (0, 1)),
    created_at      TEXT    NOT NULL,
    UNIQUE(card_id, sentence_id, source_key)
);

CREATE INDEX IF NOT EXISTS idx_word_card_sources_card
    ON word_card_sources(card_id);

CREATE INDEX IF NOT EXISTS idx_word_card_sources_sentence
    ON word_card_sources(sentence_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_word_card_sources_one_primary
    ON word_card_sources(card_id)
    WHERE is_primary = 1;

INSERT OR IGNORE INTO word_card_sources
    (card_id, sentence_id, surface_form, source_key, is_primary, created_at)
SELECT id, first_sentence_id, surface_form, lower(trim(surface_form)), 1, created_at
  FROM word_cards
 WHERE first_sentence_id IS NOT NULL;

UPDATE word_cards
   SET occurrence_count = (
       SELECT COUNT(*)
         FROM word_card_sources
        WHERE word_card_sources.card_id = word_cards.id
   )
 WHERE EXISTS (
       SELECT 1
         FROM word_card_sources
        WHERE word_card_sources.card_id = word_cards.id
   );
