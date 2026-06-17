-- Migration 007: allow PDF imports as normalized reader text.
-- SQLite cannot alter CHECK constraints in place, so rebuild books while
-- preserving all existing rows and dependent foreign-key relationships.

PRAGMA foreign_keys = OFF;

CREATE TABLE books_new (
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

INSERT INTO books_new (
    id, title, author, language, source_format, file_hash,
    imported_at, total_chapters, total_sentences
)
SELECT
    id, title, author, language, source_format, file_hash,
    imported_at, total_chapters, total_sentences
FROM books;

DROP TABLE books;
ALTER TABLE books_new RENAME TO books;

PRAGMA foreign_keys = ON;
