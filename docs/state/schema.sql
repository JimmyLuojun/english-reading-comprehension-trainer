CREATE TABLE schema_migrations (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                filename    TEXT    NOT NULL UNIQUE,
                applied_at  TEXT    NOT NULL
            , checksum TEXT);
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
CREATE TABLE IF NOT EXISTS "error_types" (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    code  TEXT    NOT NULL UNIQUE,
    name  TEXT    NOT NULL,
    layer TEXT    NOT NULL CHECK(layer IN ('grammar','lexical','discourse','inference'))
);
CREATE TABLE IF NOT EXISTS "books" (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT    NOT NULL,
    author          TEXT    NOT NULL DEFAULT '',
    language        TEXT    NOT NULL DEFAULT 'en',
    source_format   TEXT    NOT NULL CHECK(source_format IN ('txt', 'epub', 'pdf', 'md')),
    file_hash       TEXT    NOT NULL UNIQUE,
    imported_at     TEXT    NOT NULL,
    total_chapters  INTEGER NOT NULL DEFAULT 0,
    total_sentences INTEGER NOT NULL DEFAULT 0
, content_kind TEXT NOT NULL DEFAULT 'unclassified'
    CHECK(content_kind IN ('book', 'article', 'excerpt', 'unclassified')), import_method TEXT
    CHECK(import_method IS NULL OR import_method IN ('file', 'paste', 'url')), source_uri TEXT NOT NULL DEFAULT '', library_status TEXT NOT NULL DEFAULT 'inbox'
    CHECK(library_status IN ('inbox', 'reading', 'finished', 'archived')));
CREATE TABLE IF NOT EXISTS "chapter_blocks" (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id         INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    chapter_id      INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    idx             INTEGER NOT NULL,
    kind            TEXT    NOT NULL
                            CHECK(kind IN (
                                'prose', 'heading', 'list_item', 'pre', 'table',
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
CREATE TABLE IF NOT EXISTS "word_card_sources" (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id         INTEGER NOT NULL REFERENCES word_cards(id) ON DELETE CASCADE,
    sentence_id     INTEGER NOT NULL REFERENCES sentences(id) ON DELETE CASCADE,
    surface_form    TEXT    NOT NULL,
    source_key      TEXT    NOT NULL,
    start_offset    INTEGER,
    end_offset      INTEGER,
    selected_text   TEXT    NOT NULL DEFAULT '',
    is_primary      INTEGER NOT NULL DEFAULT 0 CHECK(is_primary IN (0, 1)),
    created_at      TEXT    NOT NULL, sense_id INTEGER REFERENCES word_senses(id) ON DELETE SET NULL, context_analysis_id INTEGER REFERENCES ai_cache(id) ON DELETE SET NULL, resolution_status TEXT NOT NULL DEFAULT ''
    CHECK(resolution_status IN ('', 'matched', 'new', 'uncertain', 'manual')), resolution_confidence REAL
    CHECK(
        resolution_confidence IS NULL
        OR (resolution_confidence >= 0.0 AND resolution_confidence <= 1.0)
    ),
    CHECK (
        (start_offset IS NULL AND end_offset IS NULL)
        OR (start_offset >= 0 AND end_offset > start_offset)
    )
);
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
CREATE TABLE book_tags (
    book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    tag_id  INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY(book_id, tag_id)
);
CREATE INDEX idx_books_content_kind ON books(content_kind);
CREATE INDEX idx_books_library_status ON books(library_status);
CREATE INDEX idx_book_tags_tag ON book_tags(tag_id);
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
