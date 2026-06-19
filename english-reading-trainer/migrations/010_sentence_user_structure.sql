-- Migration 010: learner-written sentence structure attempts.
-- Structure practice is stored beside translations but does not feed Review.

ALTER TABLE sentence_cards ADD COLUMN user_structure TEXT;
ALTER TABLE sentence_cards ADD COLUMN structure_created_at TEXT;
