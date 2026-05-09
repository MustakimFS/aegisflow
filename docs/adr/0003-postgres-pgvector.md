# ADR-0003: pgvector instead of a dedicated vector DB

**Status**: accepted
**Date**: 2026-02-25

## Context

The semantic memory service needs a vector store. The market offers Pinecone,
Weaviate, Qdrant, Milvus, Chroma - and pgvector inside Postgres.

## Decision

Use pgvector. Build the abstraction so we can swap to a dedicated vector DB
in a single sprint if scale demands it.

## Rationale

1. **One store, one operational story.** Workflow runs, replay events,
   memory chunks, and tenant metadata all live in Postgres. Backup, restore,
   schema migration, point-in-time recovery - all work the same way.
2. **Joins.** The most common memory query is "find docs similar to X
   *where tenant_id = Y and namespace = Z and created_at > T*". A separate
   vector DB requires a two-step query and joining in code. pgvector does
   it in one SQL statement.
3. **HNSW is good enough.** For up to ~10M vectors, pgvector's HNSW
   implementation has acceptable recall and latency. Beyond that we revisit.
4. **No new vendor.** Customers already have Postgres expertise. Adding a
   Pinecone account, an API key, a new failure mode - that's a sales
   objection we don't need.

## Costs we accept

- Vector ops compete with OLTP queries on the same node. We'll need read
  replicas dedicated to memory once retrieval QPS climbs.
- pgvector's HNSW build is slower than dedicated vector DBs at the 100M+
  scale. Acceptable trade-off given our target scale.

## Alternatives considered

- **Pinecone**: best DX, vendor lock-in, expensive at scale, can't run in
  customer clusters.
- **Qdrant / Weaviate**: solid open-source options, but adding another
  stateful service to operate.
- **FAISS in-process**: no persistence, no concurrency, fits demos only.

## Revisit when

- Memory queries cross 1k QPS sustained, OR
- Vector index size exceeds 10M chunks per tenant, OR
- A customer requires a specific vector DB for procurement reasons.
