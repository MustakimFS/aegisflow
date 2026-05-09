"""Append-only event log. Source of truth for replay + audit."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import asyncpg

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS replay_events (
    seq BIGSERIAL PRIMARY KEY,
    trace_id TEXT NOT NULL,
    run_id TEXT,
    node_id TEXT,
    kind TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS replay_events_trace_idx ON replay_events (trace_id, seq);
CREATE INDEX IF NOT EXISTS replay_events_run_idx ON replay_events (run_id, seq);
"""


class EventStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def append(
        self,
        *,
        trace_id: str,
        run_id: str | None,
        node_id: str | None,
        kind: str,
        payload: dict[str, Any],
    ) -> int:
        async with self._pool.acquire() as conn:
            seq = await conn.fetchval(
                """
                INSERT INTO replay_events (trace_id, run_id, node_id, kind, payload)
                VALUES ($1, $2, $3, $4, $5::jsonb)
                RETURNING seq
                """,
                trace_id,
                run_id,
                node_id,
                kind,
                json.dumps(payload, default=str),
            )
        return int(seq)

    async def fetch(self, trace_id: str) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT seq, trace_id, run_id, node_id, kind, payload, created_at
                FROM replay_events
                WHERE trace_id = $1
                ORDER BY seq
                """,
                trace_id,
            )
        return [
            {
                "seq": r["seq"],
                "trace_id": r["trace_id"],
                "run_id": r["run_id"],
                "node_id": r["node_id"],
                "kind": r["kind"],
                "payload": _parse(r["payload"]),
                "created_at": r["created_at"].astimezone(UTC).isoformat(),
            }
            for r in rows
        ]


def _parse(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {"raw": value}
    return {}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()
