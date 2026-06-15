-- Migration 005: separate reading order from displayed chapter numbering.
-- EPUBs often include frontmatter/backmatter in spine reading order. These
-- rows should remain readable without consuming body chapter numbers.

ALTER TABLE chapters
ADD COLUMN section_kind TEXT NOT NULL DEFAULT 'chapter'
    CHECK(section_kind IN ('frontmatter', 'chapter', 'appendix', 'backmatter'));

ALTER TABLE chapters
ADD COLUMN chapter_number INTEGER;

UPDATE chapters
   SET chapter_number = idx
 WHERE section_kind = 'chapter'
   AND chapter_number IS NULL;
