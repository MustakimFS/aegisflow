"""Chaos service entrypoint.

The chaos service is a *passive* coordinator - it never reaches into other
services. The orchestrator opts in by polling `/v1/chaos/decide/{provider}`,
and the chaos service rolls dice against active scenarios.
"""

from __future__ import annotations

import os
import random
from contextlib import asynccontextmanager
from typing import Any

from aegis_core.logging import get_logger, init_logging
from aegis_core.metrics import CHAOS_INJECTIONS, REGISTRY
from aegis_core.tracing import init_tracing
from fastapi import FastAPI, HTTPException, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from chaos.scenarios import FailureMode, Scenario, builtin_scenarios

log = get_logger("chaos")


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    init_logging("chaos")
    init_tracing("chaos")
    enabled = os.environ.get("CHAOS_ENABLED", "false").lower() == "true"
    app.state.registry = builtin_scenarios()
    app.state.master_enabled = enabled
    log.info("chaos.startup", enabled=enabled)
    yield
    log.info("chaos.shutdown")


app = FastAPI(title="AegisFlow Chaos", version="0.1.0", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> dict[str, str]:
    return {"status": "ready"}


@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


@app.get("/v1/chaos/scenarios")
async def list_scenarios() -> dict[str, Any]:
    reg = app.state.registry
    return {
        "master_enabled": app.state.master_enabled,
        "scenarios": [_scenario_to_dict(s) for s in reg.list()],
    }


@app.post("/v1/chaos/scenarios/{name}/enable")
async def enable_scenario(name: str) -> dict[str, Any]:
    return _toggle(name, enabled=True)


@app.post("/v1/chaos/scenarios/{name}/disable")
async def disable_scenario(name: str) -> dict[str, Any]:
    return _toggle(name, enabled=False)


@app.get("/v1/chaos/decide/{provider}")
async def decide(provider: str) -> dict[str, Any]:
    if not app.state.master_enabled:
        return {"inject": False}
    candidates = app.state.registry.for_provider(provider)
    for s in candidates:
        if random.random() < s.probability:
            CHAOS_INJECTIONS.labels(s.name).inc()
            return {
                "inject": True,
                "scenario": s.name,
                "failure_mode": s.failure_mode.value,
            }
    return {"inject": False}


def _toggle(name: str, *, enabled: bool) -> dict[str, Any]:
    reg = app.state.registry
    s = reg.scenarios.get(name)
    if s is None:
        raise HTTPException(status_code=404, detail=f"unknown scenario: {name}")
    new_s = Scenario(
        name=s.name,
        description=s.description,
        target_providers=s.target_providers,
        failure_mode=s.failure_mode,
        probability=s.probability,
        enabled=enabled,
    )
    reg.add(new_s)
    log.info("chaos.scenario_toggled", name=name, enabled=enabled)
    return _scenario_to_dict(new_s)


def _scenario_to_dict(s: Scenario) -> dict[str, Any]:
    return {
        "name": s.name,
        "description": s.description,
        "target_providers": list(s.target_providers),
        "failure_mode": s.failure_mode.value,
        "probability": s.probability,
        "enabled": s.enabled,
    }


# Allow modules outside this package to import FailureMode without separate path.
__all__ = ["FailureMode", "app"]
