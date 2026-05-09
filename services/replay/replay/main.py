"""Replay service entrypoint."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

import asyncpg
from aegis_core.logging import get_logger, init_logging
from aegis_core.metrics import REGISTRY
from aegis_core.tracing import init_tracing
from fastapi import FastAPI, HTTPException, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from replay.diff import diff_runs
from replay.store import SCHEMA_SQL, EventStore

log = get_logger("replay")


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    init_logging("replay")
    init_tracing("replay")

    dsn = os.environ.get(
        "POSTGRES_DSN",
        "postgresql://aegis:devonly_change_me@postgres:5432/aegisflow",
    )
    pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10)
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)

    app.state.pool = pool
    app.state.store = EventStore(pool)

    log.info("replay.startup")
    try:
        yield
    finally:
        await pool.close()
        log.info("replay.shutdown")


app = FastAPI(title="AegisFlow Replay", version="0.1.0", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> dict[str, str]:
    return {"status": "ready"}


@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


@app.post("/v1/events")
async def append_event(payload: dict[str, Any]) -> dict[str, int]:
    seq = await app.state.store.append(
        trace_id=payload["trace_id"],
        run_id=payload.get("run_id"),
        node_id=payload.get("node_id"),
        kind=payload["kind"],
        payload=payload,
    )
    return {"seq": seq}


@app.get("/v1/replay/{trace_id}")
async def replay(trace_id: str) -> dict[str, Any]:
    events = await app.state.store.fetch(trace_id)
    if not events:
        raise HTTPException(status_code=404, detail=f"no events for trace {trace_id}")
    return {"trace_id": trace_id, "events": events, "count": len(events)}


@app.post("/v1/diff")
async def diff(payload: dict[str, Any]) -> dict[str, Any]:
    left_id = payload["left_trace_id"]
    right_id = payload["right_trace_id"]
    left = await app.state.store.fetch(left_id)
    right = await app.state.store.fetch(right_id)
    return diff_runs(left, right)
