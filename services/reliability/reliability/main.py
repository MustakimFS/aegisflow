"""Reliability service entrypoint. Pure-CPU; stateless except for an in-memory provider history."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from aegis_core.logging import get_logger, init_logging
from aegis_core.metrics import REGISTRY
from aegis_core.schemas import AgentInvocation, AgentOutput, Policies
from aegis_core.tracing import init_tracing
from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from reliability.score import ProviderHistory, score

log = get_logger("reliability")


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    init_logging("reliability")
    init_tracing("reliability")
    app.state.history = ProviderHistory()
    log.info("reliability.startup")
    yield
    log.info("reliability.shutdown")


app = FastAPI(title="AegisFlow Reliability", version="0.1.0", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> dict[str, str]:
    return {"status": "ready"}


@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


@app.post("/v1/score")
async def score_endpoint(payload: dict[str, Any]) -> dict[str, Any]:
    workflow = payload["workflow"]
    invocation = AgentInvocation.model_validate(payload["invocation"])
    output = AgentOutput.model_validate(payload["output"])
    policies = Policies.model_validate(payload["policies"])

    report = score(
        workflow=workflow,
        invocation=invocation,
        output=output,
        policies=policies,
        history=app.state.history,
    )

    # Update history based on the report's verdict - accepted = success.
    app.state.history.observe(
        invocation.provider, ok=report.recommended_action.value == "accept"
    )

    return report.model_dump()
