-- Migration 004: user-translation driven sentence diagnosis.
-- Implements docs/design.md §15.3 without rewriting existing cards.

ALTER TABLE sentence_cards ADD COLUMN user_translation TEXT;
ALTER TABLE sentence_cards ADD COLUMN translation_created_at TEXT;
