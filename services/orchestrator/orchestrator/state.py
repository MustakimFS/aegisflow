"""Workflow run persistence. Postgres is the source of truth for run state."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import asyncpg
from aegis_core.schemas import WorkflowRun, WorkflowStatus


class RunStore:
    """Thin async repository over the `workflow_runs` table.

    Schema (created by migrations on first boot):

        CREATE TABLE workflow_runs (
            run_id TEXT PRIMARY KEY,
            trace_id TEXT NOT NULL,
            workflow TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TIMESTAMPTZ NOT NULL,
            finished_at TIMESTAMPTZ,
            request JSONB NOT NULL,
            response JSONB,
            node_states JSONB NOT NULL DEFAULT '{}'::jsonb,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX ON workflow_runs (tenant_id, started_at DESC);
        CREATE INDEX ON workflow_runs (trace_id);
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def insert(self, tenant_id: str, run: WorkflowRun) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO workflow_runs
                  (run_id, trace_id, workflow, tenant_id, status,
                   started_at, request, node_states)
                VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb)
                """,
                run.run_id,
                run.trace_id,
                run.workflow,
                tenant_id,
                run.status.value,
                run.started_at,
                run.request.model_dump_json(),
                "{}",
            )

    async def update_status(self, run_id: str, status: WorkflowStatus) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE workflow_runs SET status = $2, updated_at = now() WHERE run_id = $1",
                run_id,
                status.value,
            )

    async def finish(
        self,
        run_id: str,
        status: WorkflowStatus,
        response: dict[str, Any],
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE workflow_runs
                SET status = $2,
                    response = $3::jsonb,
                    finished_at = $4,
                    updated_at = now()
                WHERE run_id = $1
                """,
                run_id,
                status.value,
                _json_dumps(response),
                datetime.now(UTC),
            )

    async def get(self, run_id: str) -> dict[str, Any] | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM workflow_runs WHERE run_id = $1", run_id
            )
            return dict(row) if row else None


def _json_dumps(obj: object) -> str:
    return json.dumps(obj, default=str)


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS workflow_runs (
    run_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    workflow TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    request JSONB NOT NULL,
    response JSONB,
    node_states JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS workflow_runs_tenant_started_idx
    ON workflow_runs (tenant_id, started_at DESC);
CREATE INDEX IF NOT EXISTS workflow_runs_trace_idx
    ON workflow_runs (trace_id);
"""
