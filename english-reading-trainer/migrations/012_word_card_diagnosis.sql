-- Migration 012: persist a word card's diagnosed misconception (gap C).
--
-- The learner's own wrong understanding already lives in word_cards.user_note.
-- These columns record the latest analysis verdict on that note so review can
-- test the discrimination (what you thought vs. the correct contextual sense)
-- instead of mere recognition.
--
--   note_status     — learner_note_check.status from the latest word analysis
--                     ('' when never analysed / no note provided)
--   note_correction — AI's corrected_understanding, kept only when the note was
--                     judged a misreading; the contrast surfaced during review

ALTER TABLE word_cards ADD COLUMN note_status TEXT NOT NULL DEFAULT '';
ALTER TABLE word_cards ADD COLUMN note_correction TEXT NOT NULL DEFAULT '';
