"""Semantic memory service entrypoint."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import asyncpg
from aegis_core.logging import get_logger, init_logging
from aegis_core.metrics import REGISTRY
from aegis_core.tracing import init_tracing
from fastapi import FastAPI, Header, HTTPException, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from memory.embeddings import HashingEmbedder
from memory.ranker import rerank
from memory.vector_store import VectorStore

log = get_logger("memory")


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    init_logging("memory")
    init_tracing("memory")

    dsn = os.environ.get(
        "POSTGRES_DSN",
        "postgresql://aegis:devonly_change_me@postgres:5432/aegisflow",
    )
    pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10)
    schema = (Path(__file__).parent / "schema.sql").read_text()
    async with pool.acquire() as conn:
        try:
            await conn.execute(schema)
        except asyncpg.PostgresError as exc:
            log.warning("memory.schema_init_skipped", err=str(exc))

    app.state.pool = pool
    app.state.embedder = HashingEmbedder(dim=384)
    app.state.store = VectorStore(pool)

    log.info("memory.startup")
    try:
        yield
    finally:
        await pool.close()
        log.info("memory.shutdown")


app = FastAPI(title="AegisFlow Memory", version="0.1.0", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> dict[str, str]:
    try:
        async with app.state.pool.acquire() as conn:
            await conn.execute("SELECT 1")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"status": "ready"}


@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


@app.post("/v1/upsert")
async def upsert(
    payload: dict[str, Any],
    x_tenant_id: str = Header(default="anon"),
) -> dict[str, Any]:
    items = payload.get("items", [])
    if not items:
        return {"inserted": 0}
    embeddings = await app.state.embedder.embed([i["text"] for i in items])
    inserted = await app.state.store.upsert(x_tenant_id, items, embeddings)
    return {"inserted": inserted}


@app.post("/v1/retrieve")
async def retrieve(
    payload: dict[str, Any],
    x_tenant_id: str = Header(default="anon"),
) -> dict[str, Any]:
    query = payload["query"]
    k = int(payload.get("k", 5))
    namespace = payload.get("namespace", "default")
    embedding = (await app.state.embedder.embed([query]))[0]
    hits = await app.state.store.search(
        x_tenant_id, embedding, k=k, namespace=namespace
    )
    hits = rerank(query, hits)
    return {"hits": hits, "count": len(hits)}
