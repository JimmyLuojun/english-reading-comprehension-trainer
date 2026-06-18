-- Migration 009: add inference error layer.
-- Rebuilds error_types to relax the layer CHECK constraint, then seeds I01/I02.

PRAGMA foreign_keys = OFF;

DROP TABLE IF EXISTS error_types_new;

CREATE TABLE error_types_new (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    code  TEXT    NOT NULL UNIQUE,
    name  TEXT    NOT NULL,
    layer TEXT    NOT NULL CHECK(layer IN ('grammar','lexical','discourse','inference'))
);

INSERT INTO error_types_new (id, code, name, layer)
SELECT id, code, name, layer
FROM error_types;

DROP TABLE error_types;

ALTER TABLE error_types_new RENAME TO error_types;

INSERT OR IGNORE INTO error_types (code, name, layer) VALUES
    ('I01', '隐含关系推断失败',        'inference'),
    ('I02', '言外之意 / 立场推断失败', 'inference');

PRAGMA foreign_keys = ON;
