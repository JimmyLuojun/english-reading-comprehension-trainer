-- Migration 006: preserve EPUB media assets and reading-order blocks.
-- Text-backed blocks keep using paragraphs/sentences for review workflows;
-- this layer only records original block order and non-text media.

CREATE TABLE IF NOT EXISTS book_assets (
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

CREATE INDEX IF NOT EXISTS idx_book_assets_book
    ON book_assets(book_id);

CREATE TABLE IF NOT EXISTS chapter_blocks (
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

CREATE INDEX IF NOT EXISTS idx_chapter_blocks_book
    ON chapter_blocks(book_id);

CREATE INDEX IF NOT EXISTS idx_chapter_blocks_chapter
    ON chapter_blocks(chapter_id, idx);
