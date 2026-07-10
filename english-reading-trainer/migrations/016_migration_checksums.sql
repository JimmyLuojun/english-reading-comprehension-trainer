-- Migration 016: make applied migration contents tamper-evident.

ALTER TABLE schema_migrations ADD COLUMN checksum TEXT;
