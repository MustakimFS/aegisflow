-- pgvector is required. Compose runs `pgvector/pgvector:pg16` which has it pre-installed.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS memory_chunks (
    id BIGSERIAL PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    namespace TEXT NOT NULL DEFAULT 'default',
    text TEXT NOT NULL,
    embedding vector(384) NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS memory_chunks_tenant_idx
    ON memory_chunks (tenant_id, namespace);

-- HNSW for sub-linear ANN search at scale.
CREATE INDEX IF NOT EXISTS memory_chunks_embedding_hnsw_idx
    ON memory_chunks USING hnsw (embedding vector_cosine_ops);
