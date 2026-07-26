-- Migration 018: preserve multiple contextual senses under one review card.
--
-- word_cards remains the lemma-level review unit. word_senses stores stable
-- meanings, while word_card_sources points at the meaning and contextual
-- analysis for one exact occurrence. Existing single-analysis columns remain
-- as compatibility mirrors during the transition.

CREATE TABLE word_senses (
    id                         INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id                    INTEGER NOT NULL REFERENCES word_cards(id) ON DELETE CASCADE,
    meaning_en                 TEXT    NOT NULL,
    meaning_zh                 TEXT    NOT NULL DEFAULT '',
    pos                        TEXT    NOT NULL DEFAULT '',
    representative_analysis_id INTEGER REFERENCES ai_cache(id) ON DELETE SET NULL,
    created_at                 TEXT    NOT NULL,
    updated_at                 TEXT    NOT NULL
);

CREATE INDEX idx_word_senses_card
    ON word_senses(card_id, id);

ALTER TABLE word_card_sources
ADD COLUMN sense_id INTEGER REFERENCES word_senses(id) ON DELETE SET NULL;

ALTER TABLE word_card_sources
ADD COLUMN context_analysis_id INTEGER REFERENCES ai_cache(id) ON DELETE SET NULL;

ALTER TABLE word_card_sources
ADD COLUMN resolution_status TEXT NOT NULL DEFAULT ''
    CHECK(resolution_status IN ('', 'matched', 'new', 'uncertain', 'manual'));

ALTER TABLE word_card_sources
ADD COLUMN resolution_confidence REAL
    CHECK(
        resolution_confidence IS NULL
        OR (resolution_confidence >= 0.0 AND resolution_confidence <= 1.0)
    );

CREATE INDEX idx_word_card_sources_sense
    ON word_card_sources(sense_id);

CREATE TRIGGER word_card_sources_sense_card_insert
BEFORE INSERT ON word_card_sources
WHEN NEW.sense_id IS NOT NULL
 AND NOT EXISTS (
       SELECT 1
         FROM word_senses ws
        WHERE ws.id = NEW.sense_id
          AND ws.card_id = NEW.card_id
 )
BEGIN
    SELECT RAISE(ABORT, 'word source sense belongs to another card');
END;

CREATE TRIGGER word_card_sources_sense_card_update
BEFORE UPDATE OF sense_id, card_id ON word_card_sources
WHEN NEW.sense_id IS NOT NULL
 AND NOT EXISTS (
       SELECT 1
         FROM word_senses ws
        WHERE ws.id = NEW.sense_id
          AND ws.card_id = NEW.card_id
 )
BEGIN
    SELECT RAISE(ABORT, 'word source sense belongs to another card');
END;

-- Every valid legacy card analysis becomes the first stable sense. JSON fields
-- are copied because ai_cache rows are mutable cache artifacts, not identities.
INSERT INTO word_senses (
    card_id,
    meaning_en,
    meaning_zh,
    pos,
    representative_analysis_id,
    created_at,
    updated_at
)
SELECT wc.id,
       COALESCE(NULLIF(json_extract(ac.response_json, '$.meaning_in_context'), ''),
                NULLIF(wc.current_meaning, ''),
                wc.surface_form),
       COALESCE(json_extract(ac.response_json, '$.chinese_meaning'), ''),
       COALESCE(NULLIF(json_extract(ac.response_json, '$.pos'), ''), wc.pos, ''),
       ac.id,
       ac.created_at,
       ac.created_at
  FROM word_cards wc
  JOIN ai_cache ac
    ON ac.id = wc.ai_analysis_id
   AND ac.is_valid = 1;

-- Only the explicit primary occurrence is safe to backfill automatically.
-- Other historical occurrences remain unclassified until the learner opens
-- or analyzes them.
UPDATE word_card_sources
   SET sense_id = (
           SELECT ws.id
             FROM word_senses ws
            WHERE ws.card_id = word_card_sources.card_id
            ORDER BY ws.id
            LIMIT 1
       ),
       context_analysis_id = (
           SELECT wc.ai_analysis_id
             FROM word_cards wc
            WHERE wc.id = word_card_sources.card_id
       ),
       resolution_status = 'manual',
       resolution_confidence = 1.0
 WHERE is_primary = 1
   AND EXISTS (
       SELECT 1
         FROM word_senses ws
        WHERE ws.card_id = word_card_sources.card_id
   );
