"""Orchestrator service entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

import asyncpg
import httpx
from aegis_core.ids import new_run_id, new_trace_id
from aegis_core.logging import get_logger, init_logging
from aegis_core.metrics import REGISTRY
from aegis_core.schemas import WorkflowRequest, WorkflowRun, WorkflowStatus
from aegis_core.tracing import init_tracing
from fastapi import FastAPI, HTTPException, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from orchestrator.engine import Engine
from orchestrator.llm_client import LLMClient, ProviderConfig
from orchestrator.settings import load_settings
from orchestrator.state import SCHEMA_SQL, RunStore
from orchestrator.workflows import REGISTRY as WORKFLOW_REGISTRY

log = get_logger("orchestrator")


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    settings = load_settings()
    init_logging("orchestrator")
    init_tracing("orchestrator")

    pool = await asyncpg.create_pool(settings.postgres_dsn, min_size=2, max_size=10)
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)

    http_client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=2.0))
    llm = LLMClient(
        configs=[
            ProviderConfig(name="mock", model="mock-1"),
            ProviderConfig(name="openai", model="gpt-4o-mini", api_key_env="OPENAI_API_KEY"),
        ],
        chaos_url=settings.chaos_url,
    )
    engine = Engine(
        llm=llm,
        run_store=RunStore(pool),
        http_client=http_client,
        reliability_url=settings.reliability_url,
        guardrails_url=settings.guardrails_url,
        memory_url=settings.memory_url,
        replay_url=settings.replay_url,
        workflows=WORKFLOW_REGISTRY,
    )

    app.state.settings = settings
    app.state.pool = pool
    app.state.http_client = http_client
    app.state.engine = engine
    app.state.run_store = RunStore(pool)

    log.info("orchestrator.startup", port=settings.orchestrator_port)
    try:
        yield
    finally:
        await http_client.aclose()
        await pool.close()
        log.info("orchestrator.shutdown")


app = FastAPI(title="AegisFlow Orchestrator", version="0.1.0", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
async def readyz(request: Request) -> dict[str, str]:
    try:
        async with request.app.state.pool.acquire() as conn:
            await conn.execute("SELECT 1")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"postgres: {exc}") from exc
    return {"status": "ready"}


@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


@app.post("/v1/workflows")
async def submit(request: Request, payload: dict) -> dict:  # type: ignore[type-arg]
    body = WorkflowRequest.model_validate(payload)
    tenant_id = request.headers.get("x-tenant-id", "anon")
    trace_id = request.headers.get("x-trace-id") or new_trace_id()
    run_id = new_run_id()
    run = WorkflowRun.new(body, run_id=run_id, trace_id=trace_id)
    await request.app.state.run_store.insert(tenant_id, run)

    wf = WORKFLOW_REGISTRY.get(body.workflow)
    if wf is None:
        await request.app.state.run_store.finish(
            run.run_id, WorkflowStatus.FAILED, {"error": "unknown_workflow"}
        )
        raise HTTPException(status_code=400, detail=f"unknown workflow: {body.workflow}")

    policies = body.policies or wf.default_policies
    response = await request.app.state.engine.execute(run, tenant_id, policies)
    return response.model_dump()
