-- Migration 003: soft-delete cards for selection-based reader interactions.
-- Implements docs/design.md §14.6 without destroying review history.

ALTER TABLE sentence_cards ADD COLUMN archived_at TEXT;
ALTER TABLE word_cards ADD COLUMN archived_at TEXT;

CREATE INDEX IF NOT EXISTS idx_sentence_cards_active_due
    ON sentence_cards(archived_at, due_at);

CREATE INDEX IF NOT EXISTS idx_word_cards_active_due
    ON word_cards(archived_at, due_at);
