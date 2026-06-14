-- Migration 001: initial schema
-- Matches §1 of docs/design.md exactly.
-- Run via db_connection.py::apply_migrations() — idempotent.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- Text hierarchy
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS books (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT    NOT NULL,
    author          TEXT    NOT NULL DEFAULT '',
    language        TEXT    NOT NULL DEFAULT 'en',
    source_format   TEXT    NOT NULL CHECK(source_format IN ('txt', 'epub')),
    file_hash       TEXT    NOT NULL UNIQUE,
    imported_at     TEXT    NOT NULL,   -- ISO-8601
    total_chapters  INTEGER NOT NULL DEFAULT 0,
    total_sentences INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS chapters (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id         INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    idx             INTEGER NOT NULL,
    title           TEXT    NOT NULL DEFAULT '',
    sentence_start  INTEGER NOT NULL DEFAULT 0,
    sentence_end    INTEGER NOT NULL DEFAULT 0,
    UNIQUE(book_id, idx)
);

CREATE TABLE IF NOT EXISTS paragraphs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter_id      INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    idx             INTEGER NOT NULL,
    sentence_start  INTEGER NOT NULL DEFAULT 0,
    sentence_end    INTEGER NOT NULL DEFAULT 0,
    UNIQUE(chapter_id, idx)
);

CREATE TABLE IF NOT EXISTS sentences (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id             INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    chapter_id          INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    paragraph_id        INTEGER NOT NULL REFERENCES paragraphs(id) ON DELETE CASCADE,
    idx                 INTEGER NOT NULL,
    text                TEXT    NOT NULL,
    text_hash           TEXT    NOT NULL,   -- SHA256 of normalised text; non-unique (cross-book)
    char_offset_start   INTEGER NOT NULL DEFAULT 0,
    char_offset_end     INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_sentences_book        ON sentences(book_id);
CREATE INDEX IF NOT EXISTS idx_sentences_text_hash   ON sentences(text_hash);

-- ---------------------------------------------------------------------------
-- Cards (SM-2 scheduling fields: ef / interval_days / repetitions)
-- mastery_state is derived from SM-2 state — see §7.4 of design.md
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS sentence_cards (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    sentence_id         INTEGER NOT NULL REFERENCES sentences(id) ON DELETE CASCADE,
    created_at          TEXT    NOT NULL,
    last_reviewed_at    TEXT,
    review_count        INTEGER NOT NULL DEFAULT 0,
    mastery_state       TEXT    NOT NULL DEFAULT 'new'
                            CHECK(mastery_state IN ('new','learning','mature','lapsed')),
    ef                  REAL    NOT NULL DEFAULT 2.5,
    interval_days       INTEGER NOT NULL DEFAULT 0,
    repetitions         INTEGER NOT NULL DEFAULT 0,
    due_at              TEXT    NOT NULL,
    user_note           TEXT    NOT NULL DEFAULT '',
    ai_analysis_id      INTEGER REFERENCES ai_cache(id) ON DELETE SET NULL,
    UNIQUE(sentence_id)   -- one card per sentence
);

CREATE INDEX IF NOT EXISTS idx_sentence_cards_due ON sentence_cards(due_at);

CREATE TABLE IF NOT EXISTS word_cards (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    lemma               TEXT    NOT NULL,
    surface_form        TEXT    NOT NULL,
    lexical_type        TEXT    NOT NULL DEFAULT 'word'
                            CHECK(lexical_type IN ('word','phrase','collocation')),
    first_sentence_id   INTEGER NOT NULL REFERENCES sentences(id) ON DELETE RESTRICT,
    current_meaning     TEXT    NOT NULL DEFAULT '',
    pos                 TEXT    NOT NULL DEFAULT '',
    created_at          TEXT    NOT NULL,
    last_reviewed_at    TEXT,
    review_count        INTEGER NOT NULL DEFAULT 0,
    mastery_state       TEXT    NOT NULL DEFAULT 'new'
                            CHECK(mastery_state IN ('new','learning','mature','lapsed')),
    ef                  REAL    NOT NULL DEFAULT 2.5,
    interval_days       INTEGER NOT NULL DEFAULT 0,
    repetitions         INTEGER NOT NULL DEFAULT 0,
    due_at              TEXT    NOT NULL,
    occurrence_count    INTEGER NOT NULL DEFAULT 1,
    user_note           TEXT    NOT NULL DEFAULT '',
    ai_analysis_id      INTEGER REFERENCES ai_cache(id) ON DELETE SET NULL,
    UNIQUE(lemma)         -- one card per lemma
);

CREATE INDEX IF NOT EXISTS idx_word_cards_due     ON word_cards(due_at);
CREATE INDEX IF NOT EXISTS idx_word_cards_lemma   ON word_cards(lemma);
CREATE INDEX IF NOT EXISTS idx_word_cards_surface ON word_cards(surface_form);

-- ---------------------------------------------------------------------------
-- Review log — records SM-2 state before and after each review
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS review_logs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    card_type           TEXT    NOT NULL CHECK(card_type IN ('sentence','word')),
    card_id             INTEGER NOT NULL,
    reviewed_at         TEXT    NOT NULL,
    quality             INTEGER NOT NULL CHECK(quality BETWEEN 0 AND 5),
    outcome             TEXT    NOT NULL CHECK(outcome IN ('pass','partial','fail')),
    ef_before           REAL    NOT NULL,
    ef_after            REAL    NOT NULL,
    interval_before     INTEGER NOT NULL,
    interval_after      INTEGER NOT NULL,
    repetitions_before  INTEGER NOT NULL,
    repetitions_after   INTEGER NOT NULL,
    latency_ms          INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_review_logs_card ON review_logs(card_type, card_id);

-- ---------------------------------------------------------------------------
-- Tags (user-defined) and error types (closed enumeration, seeded separately)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS tags (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name     TEXT    NOT NULL UNIQUE,
    category TEXT    NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS error_types (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    code  TEXT    NOT NULL UNIQUE,  -- e.g. G01, L03, D02
    name  TEXT    NOT NULL,
    layer TEXT    NOT NULL CHECK(layer IN ('grammar','lexical','discourse'))
);

-- Many-to-many: sentence cards ↔ tags / error types
CREATE TABLE IF NOT EXISTS sentence_card_tags (
    card_id INTEGER NOT NULL REFERENCES sentence_cards(id) ON DELETE CASCADE,
    tag_id  INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY(card_id, tag_id)
);

CREATE TABLE IF NOT EXISTS sentence_card_errors (
    card_id       INTEGER NOT NULL REFERENCES sentence_cards(id) ON DELETE CASCADE,
    error_type_id INTEGER NOT NULL REFERENCES error_types(id) ON DELETE CASCADE,
    PRIMARY KEY(card_id, error_type_id)
);

-- Many-to-many: word cards ↔ tags / error types
CREATE TABLE IF NOT EXISTS word_card_tags (
    card_id INTEGER NOT NULL REFERENCES word_cards(id) ON DELETE CASCADE,
    tag_id  INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY(card_id, tag_id)
);

CREATE TABLE IF NOT EXISTS word_card_errors (
    card_id       INTEGER NOT NULL REFERENCES word_cards(id) ON DELETE CASCADE,
    error_type_id INTEGER NOT NULL REFERENCES error_types(id) ON DELETE CASCADE,
    PRIMARY KEY(card_id, error_type_id)
);

-- ---------------------------------------------------------------------------
-- AI response cache (§5 of design.md)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS ai_cache (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    content_hash    TEXT    NOT NULL,
    prompt_version  TEXT    NOT NULL,
    model           TEXT    NOT NULL,
    response_json   TEXT    NOT NULL,
    is_valid        INTEGER NOT NULL DEFAULT 1 CHECK(is_valid IN (0,1)),
    created_at      TEXT    NOT NULL,
    UNIQUE(content_hash, prompt_version, model)
);

-- ---------------------------------------------------------------------------
-- Learner profile snapshots (§11 of design.md)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS learner_profile_snapshots (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at           TEXT    NOT NULL,
    summary_md           TEXT    NOT NULL,
    payload_json         TEXT    NOT NULL DEFAULT '{}',
    cards_at_snapshot    INTEGER NOT NULL DEFAULT 0,
    sentences_at_snapshot INTEGER NOT NULL DEFAULT 0
);

-- ---------------------------------------------------------------------------
-- Prompt versions (§10 of design.md)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS prompt_versions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL,
    version    TEXT    NOT NULL,
    body_md    TEXT    NOT NULL,
    created_at TEXT    NOT NULL,
    is_active  INTEGER NOT NULL DEFAULT 0 CHECK(is_active IN (0,1)),
    UNIQUE(name, version)
);

-- ---------------------------------------------------------------------------
-- Schema version tracking (for migration runner)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS schema_migrations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    filename    TEXT    NOT NULL UNIQUE,
    applied_at  TEXT    NOT NULL
);
