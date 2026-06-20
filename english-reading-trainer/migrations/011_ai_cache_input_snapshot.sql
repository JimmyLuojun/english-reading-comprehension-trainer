-- Migration 011: preserve sentence-analysis input snapshots.
--
-- These columns store the translation/structure text used to produce a
-- sentence analysis cache row. They are nullable so historical cache rows and
-- word-analysis rows remain valid.

ALTER TABLE ai_cache ADD COLUMN input_translation TEXT;
ALTER TABLE ai_cache ADD COLUMN input_structure TEXT;
