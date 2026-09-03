PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS courses (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  file_name TEXT NOT NULL,
  file_sha256 TEXT,
  page_count INTEGER,
  extraction_version TEXT,
  chunking_version TEXT,
  embedding_model TEXT,
  embedding_dimension INTEGER,
  status TEXT NOT NULL DEFAULT 'not_indexed',
  indexed_at TEXT
);

CREATE TABLE IF NOT EXISTS source_courses (
  source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
  PRIMARY KEY (source_id, course_id)
);

CREATE TABLE IF NOT EXISTS pages (
  id INTEGER PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  physical_page INTEGER NOT NULL,
  page_label TEXT NOT NULL,
  raw_text TEXT NOT NULL,
  cleaned_text TEXT NOT NULL,
  extraction_method TEXT NOT NULL,
  character_count INTEGER NOT NULL,
  alphanumeric_ratio REAL NOT NULL,
  whitespace_ratio REAL NOT NULL,
  replacement_character_count INTEGER NOT NULL,
  diagnostic_status TEXT NOT NULL,
  UNIQUE (source_id, physical_page)
);

CREATE TABLE IF NOT EXISTS chunks (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  page_id INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
  physical_page INTEGER NOT NULL,
  page_label TEXT NOT NULL,
  ordinal INTEGER NOT NULL,
  char_start INTEGER NOT NULL,
  char_end INTEGER NOT NULL,
  content TEXT NOT NULL,
  content_sha256 TEXT NOT NULL,
  embedding BLOB NOT NULL,
  embedding_dimension INTEGER NOT NULL,
  UNIQUE (source_id, physical_page, ordinal)
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
  chunk_id UNINDEXED,
  source_id UNINDEXED,
  physical_page UNINDEXED,
  content,
  tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
  text TEXT NOT NULL,
  provider_choice TEXT,
  actual_provider TEXT,
  fallback_used INTEGER NOT NULL DEFAULT 0,
  retrieval_fallback_used INTEGER NOT NULL DEFAULT 0,
  select_all_that_apply INTEGER NOT NULL DEFAULT 0,
  initial_failure_kind TEXT,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS message_evidence (
  message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
  chunk_id TEXT NOT NULL,
  source_id TEXT NOT NULL,
  source_title TEXT NOT NULL,
  physical_page INTEGER NOT NULL,
  page_label TEXT NOT NULL,
  excerpt TEXT NOT NULL,
  rank INTEGER NOT NULL,
  semantic_score REAL,
  fts_score REAL,
  fusion_score REAL NOT NULL,
  citation_order INTEGER,
  PRIMARY KEY (message_id, chunk_id)
);

CREATE INDEX IF NOT EXISTS idx_chunks_source_page ON chunks(source_id, physical_page);
CREATE INDEX IF NOT EXISTS idx_pages_source_page ON pages(source_id, physical_page);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_conversations_updated ON conversations(updated_at DESC);

INSERT OR IGNORE INTO schema_migrations(version) VALUES (1);
