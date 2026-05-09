"""Guardrails service entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from aegis_core.logging import get_logger, init_logging
from aegis_core.metrics import GUARDRAIL_VIOLATIONS, REGISTRY
from aegis_core.tracing import init_tracing
from fastapi import FastAPI, HTTPException, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from guardrails.json_repair import RepairFailed, repair
from guardrails.sanitize import sanitize
from guardrails.schema import SchemaCache, validate

log = get_logger("guardrails")


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    init_logging("guardrails")
    init_tracing("guardrails")
    app.state.schema_cache = SchemaCache()
    log.info("guardrails.startup")
    yield
    log.info("guardrails.shutdown")


app = FastAPI(title="AegisFlow Guardrails", version="0.1.0", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> dict[str, str]:
    return {"status": "ready"}


@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


@app.post("/v1/validate")
async def validate_endpoint(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("raw", "")
    schema = payload.get("schema")

    try:
        result = repair(raw)
    except RepairFailed as exc:
        GUARDRAIL_VIOLATIONS.labels("unrepairable_json").inc()
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    parsed = result.parsed
    repaired = result.was_repaired

    if schema is not None:
        validation = validate(parsed, schema, app.state.schema_cache)
        if not validation.ok:
            GUARDRAIL_VIOLATIONS.labels("schema_failure").inc()
            return {
                "ok": False,
                "parsed": parsed,
                "repaired": repaired,
                "repairs": list(result.repairs),
                "errors": validation.errors,
            }

    return {
        "ok": True,
        "parsed": parsed,
        "repaired": repaired,
        "repairs": list(result.repairs),
    }


@app.post("/v1/sanitize")
async def sanitize_endpoint(payload: dict[str, Any]) -> dict[str, Any]:
    text = str(payload.get("text", ""))
    redact_pii = bool(payload.get("redact_pii", True))
    sanitized, actions = sanitize(text, redact_pii=redact_pii)
    if actions:
        for action in actions:
            GUARDRAIL_VIOLATIONS.labels(action).inc()
    return {"sanitized": sanitized, "actions": actions}
