CREATE TABLE schema_migrations (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename    TEXT    NOT NULL UNIQUE,
                    applied_at  TEXT    NOT NULL
                );
CREATE TABLE sqlite_sequence(name,seq);
CREATE TABLE chapters (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id         INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    idx             INTEGER NOT NULL,
    title           TEXT    NOT NULL DEFAULT '',
    sentence_start  INTEGER NOT NULL DEFAULT 0,
    sentence_end    INTEGER NOT NULL DEFAULT 0, section_kind TEXT NOT NULL DEFAULT 'chapter'
    CHECK(section_kind IN ('frontmatter', 'chapter', 'appendix', 'backmatter')), chapter_number INTEGER,
    UNIQUE(book_id, idx)
);
CREATE TABLE paragraphs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter_id      INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    idx             INTEGER NOT NULL,
    sentence_start  INTEGER NOT NULL DEFAULT 0,
    sentence_end    INTEGER NOT NULL DEFAULT 0,
    UNIQUE(chapter_id, idx)
);
CREATE TABLE sentences (
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
CREATE INDEX idx_sentences_book        ON sentences(book_id);
CREATE INDEX idx_sentences_text_hash   ON sentences(text_hash);
CREATE TABLE sentence_cards (
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
    ai_analysis_id      INTEGER REFERENCES ai_cache(id) ON DELETE SET NULL, archived_at TEXT, user_translation TEXT, translation_created_at TEXT, user_structure TEXT, structure_created_at TEXT,
    UNIQUE(sentence_id)   -- one card per sentence
);
CREATE INDEX idx_sentence_cards_due ON sentence_cards(due_at);
CREATE TABLE word_cards (
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
    ai_analysis_id      INTEGER REFERENCES ai_cache(id) ON DELETE SET NULL, archived_at TEXT, note_status TEXT NOT NULL DEFAULT '', note_correction TEXT NOT NULL DEFAULT '',
    UNIQUE(lemma)         -- one card per lemma
);
CREATE INDEX idx_word_cards_due     ON word_cards(due_at);
CREATE INDEX idx_word_cards_lemma   ON word_cards(lemma);
CREATE INDEX idx_word_cards_surface ON word_cards(surface_form);
CREATE TABLE review_logs (
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
CREATE INDEX idx_review_logs_card ON review_logs(card_type, card_id);
CREATE TABLE tags (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name     TEXT    NOT NULL UNIQUE,
    category TEXT    NOT NULL DEFAULT ''
);
CREATE TABLE sentence_card_tags (
    card_id INTEGER NOT NULL REFERENCES sentence_cards(id) ON DELETE CASCADE,
    tag_id  INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY(card_id, tag_id)
);
CREATE TABLE sentence_card_errors (
    card_id       INTEGER NOT NULL REFERENCES sentence_cards(id) ON DELETE CASCADE,
    error_type_id INTEGER NOT NULL REFERENCES error_types(id) ON DELETE CASCADE,
    PRIMARY KEY(card_id, error_type_id)
);
CREATE TABLE word_card_tags (
    card_id INTEGER NOT NULL REFERENCES word_cards(id) ON DELETE CASCADE,
    tag_id  INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY(card_id, tag_id)
);
CREATE TABLE word_card_errors (
    card_id       INTEGER NOT NULL REFERENCES word_cards(id) ON DELETE CASCADE,
    error_type_id INTEGER NOT NULL REFERENCES error_types(id) ON DELETE CASCADE,
    PRIMARY KEY(card_id, error_type_id)
);
CREATE TABLE ai_cache (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    content_hash    TEXT    NOT NULL,
    prompt_version  TEXT    NOT NULL,
    model           TEXT    NOT NULL,
    response_json   TEXT    NOT NULL,
    is_valid        INTEGER NOT NULL DEFAULT 1 CHECK(is_valid IN (0,1)),
    created_at      TEXT    NOT NULL, input_translation TEXT, input_structure TEXT,
    UNIQUE(content_hash, prompt_version, model)
);
CREATE TABLE learner_profile_snapshots (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at           TEXT    NOT NULL,
    summary_md           TEXT    NOT NULL,
    payload_json         TEXT    NOT NULL DEFAULT '{}',
    cards_at_snapshot    INTEGER NOT NULL DEFAULT 0,
    sentences_at_snapshot INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE prompt_versions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL,
    version    TEXT    NOT NULL,
    body_md    TEXT    NOT NULL,
    created_at TEXT    NOT NULL,
    is_active  INTEGER NOT NULL DEFAULT 0 CHECK(is_active IN (0,1)),
    UNIQUE(name, version)
);
CREATE INDEX idx_sentence_cards_active_due
    ON sentence_cards(archived_at, due_at);
CREATE INDEX idx_word_cards_active_due
    ON word_cards(archived_at, due_at);
CREATE TABLE book_assets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id         INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    source_href     TEXT    NOT NULL,
    media_type      TEXT    NOT NULL DEFAULT '',
    storage_path    TEXT    NOT NULL DEFAULT '',
    sha256          TEXT    NOT NULL DEFAULT '',
    byte_size       INTEGER NOT NULL DEFAULT 0,
    alt_text        TEXT    NOT NULL DEFAULT '',
    is_missing      INTEGER NOT NULL DEFAULT 0 CHECK(is_missing IN (0, 1)),
    UNIQUE(book_id, source_href)
);
CREATE INDEX idx_book_assets_book
    ON book_assets(book_id);
CREATE TABLE chapter_blocks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id         INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    chapter_id      INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    idx             INTEGER NOT NULL,
    kind            TEXT    NOT NULL
                            CHECK(kind IN (
                                'prose', 'pre', 'table',
                                'image', 'figure', 'missing_asset'
                            )),
    paragraph_id    INTEGER REFERENCES paragraphs(id) ON DELETE SET NULL,
    asset_id        INTEGER REFERENCES book_assets(id) ON DELETE SET NULL,
    text            TEXT    NOT NULL DEFAULT '',
    payload_json    TEXT    NOT NULL DEFAULT '',
    UNIQUE(chapter_id, idx)
);
CREATE INDEX idx_chapter_blocks_book
    ON chapter_blocks(book_id);
CREATE INDEX idx_chapter_blocks_chapter
    ON chapter_blocks(chapter_id, idx);
CREATE TABLE IF NOT EXISTS "books" (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT    NOT NULL,
    author          TEXT    NOT NULL DEFAULT '',
    language        TEXT    NOT NULL DEFAULT 'en',
    source_format   TEXT    NOT NULL CHECK(source_format IN ('txt', 'epub', 'pdf')),
    file_hash       TEXT    NOT NULL UNIQUE,
    imported_at     TEXT    NOT NULL,
    total_chapters  INTEGER NOT NULL DEFAULT 0,
    total_sentences INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE word_card_sources (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id         INTEGER NOT NULL REFERENCES word_cards(id) ON DELETE CASCADE,
    sentence_id     INTEGER NOT NULL REFERENCES sentences(id) ON DELETE CASCADE,
    surface_form    TEXT    NOT NULL,
    source_key      TEXT    NOT NULL,
    is_primary      INTEGER NOT NULL DEFAULT 0 CHECK(is_primary IN (0, 1)),
    created_at      TEXT    NOT NULL,
    UNIQUE(card_id, sentence_id, source_key)
);
CREATE INDEX idx_word_card_sources_card
    ON word_card_sources(card_id);
CREATE INDEX idx_word_card_sources_sentence
    ON word_card_sources(sentence_id);
CREATE UNIQUE INDEX idx_word_card_sources_one_primary
    ON word_card_sources(card_id)
    WHERE is_primary = 1;
CREATE TABLE IF NOT EXISTS "error_types" (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    code  TEXT    NOT NULL UNIQUE,
    name  TEXT    NOT NULL,
    layer TEXT    NOT NULL CHECK(layer IN ('grammar','lexical','discourse','inference'))
);
