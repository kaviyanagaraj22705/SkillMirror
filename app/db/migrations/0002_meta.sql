-- Metadata rows that are not part of the schema contract itself.

INSERT INTO app_meta (key, value) VALUES ('schema_notes', 'v1 initial schema')
  ON CONFLICT(key) DO UPDATE SET value = excluded.value;
