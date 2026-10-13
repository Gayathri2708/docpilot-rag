-- Idempotent: safe to run on every startup.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filename    TEXT        NOT NULL,
    sha256      TEXT        NOT NULL UNIQUE,   -- dedupe identical uploads
    num_chunks  INTEGER     NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Access control: each document belongs to one access group; 'all' is visible to every API key.
-- ADD COLUMN IF NOT EXISTS also upgrades databases created before access groups existed.
ALTER TABLE documents ADD COLUMN IF NOT EXISTS access_group TEXT NOT NULL DEFAULT 'all'
    CHECK (access_group IN ('all', 'hr', 'finance', 'engineering'));
CREATE INDEX IF NOT EXISTS documents_access_group ON documents (access_group);

CREATE TABLE IF NOT EXISTS api_keys (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT        NOT NULL UNIQUE,
    key_hash    TEXT        NOT NULL UNIQUE,   -- SHA-256 of the key; the key itself is never stored
    groups      TEXT[]      NOT NULL,          -- groups this key may read and write, besides 'all'
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunks (
    id           BIGSERIAL PRIMARY KEY,
    document_id  UUID    NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index  INTEGER NOT NULL,
    page         INTEGER,                      -- NULL for .txt / .md
    content      TEXT    NOT NULL,
    embedding    vector(384) NOT NULL,
    -- Full-text column for the keyword half of hybrid search.
    tsv          tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    UNIQUE (document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw
    ON chunks USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS chunks_tsv_gin
    ON chunks USING gin (tsv);
