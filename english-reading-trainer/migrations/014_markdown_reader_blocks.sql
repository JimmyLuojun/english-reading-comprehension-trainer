-- Migration 014: allow Markdown-specific text block kinds in chapter_blocks.
-- SQLite cannot alter CHECK constraints in place, so rebuild the table while
-- preserving existing EPUB/PDF block rows.

PRAGMA foreign_keys = OFF;

CREATE TABLE chapter_blocks_new (
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

INSERT INTO chapter_blocks_new (
    id, book_id, chapter_id, idx, kind, paragraph_id, asset_id, text, payload_json
)
SELECT
    id, book_id, chapter_id, idx, kind, paragraph_id, asset_id, text, payload_json
FROM chapter_blocks;

DROP TABLE chapter_blocks;
ALTER TABLE chapter_blocks_new RENAME TO chapter_blocks;

CREATE INDEX idx_chapter_blocks_book
    ON chapter_blocks(book_id);

CREATE INDEX idx_chapter_blocks_chapter
    ON chapter_blocks(chapter_id, idx);

PRAGMA foreign_keys = ON;
