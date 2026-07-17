-- Migration 017: present books as typed Library Items without changing IDs.
-- Existing rows remain honestly unclassified. Their historical import method
-- and source URI are unknown, so those fields stay NULL/empty.

ALTER TABLE books
ADD COLUMN content_kind TEXT NOT NULL DEFAULT 'unclassified'
    CHECK(content_kind IN ('book', 'article', 'excerpt', 'unclassified'));

ALTER TABLE books
ADD COLUMN import_method TEXT
    CHECK(import_method IS NULL OR import_method IN ('file', 'paste', 'url'));

ALTER TABLE books
ADD COLUMN source_uri TEXT NOT NULL DEFAULT '';

ALTER TABLE books
ADD COLUMN library_status TEXT NOT NULL DEFAULT 'inbox'
    CHECK(library_status IN ('inbox', 'reading', 'finished', 'archived'));

CREATE TABLE book_tags (
    book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    tag_id  INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY(book_id, tag_id)
);

CREATE INDEX idx_books_content_kind ON books(content_kind);
CREATE INDEX idx_books_library_status ON books(library_status);
CREATE INDEX idx_book_tags_tag ON book_tags(tag_id);
