"""Gateway entrypoint. Auth, rate-limit, trace propagation, request validation, routing."""

from __future__ import annotations

from contextlib import asynccontextmanager

import httpx
import redis.asyncio as redis
import structlog
from aegis_core.ids import new_trace_id
from aegis_core.logging import get_logger, init_logging
from aegis_core.metrics import REGISTRY
from aegis_core.tracing import init_tracing, span
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from gateway.auth import Principal, authenticate
from gateway.rate_limit import RateLimiter
from gateway.settings import Settings, load_settings

log = get_logger("gateway")


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    settings = load_settings()
    init_logging("gateway")
    init_tracing("gateway")

    redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    rate_limiter = RateLimiter(
        redis_client=redis_client,
        capacity=settings.rate_limit_burst,
        refill_rate=float(settings.rate_limit_rps),
    )
    http_client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=2.0))

    app.state.settings = settings
    app.state.redis = redis_client
    app.state.rate_limiter = rate_limiter
    app.state.http_client = http_client

    log.info("gateway.startup", port=settings.gateway_port)
    try:
        yield
    finally:
        await http_client.aclose()
        await redis_client.aclose()
        log.info("gateway.shutdown")


app = FastAPI(title="AegisFlow Gateway", version="0.1.0", lifespan=lifespan)


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_principal(request: Request, settings: Settings = Depends(get_settings)) -> Principal:
    return authenticate(request, settings)


@app.middleware("http")
async def trace_and_log(request: Request, call_next):  # type: ignore[no-untyped-def]
    """Mint a trace ID per request, bind structured logging, attach to response."""
    trace_id = request.headers.get("x-trace-id") or new_trace_id()
    structlog.contextvars.bind_contextvars(trace_id=trace_id, path=request.url.path)
    request.state.trace_id = trace_id
    response: Response = await call_next(request)
    response.headers["x-trace-id"] = trace_id
    structlog.contextvars.unbind_contextvars("trace_id", "path")
    return response


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
async def readyz(request: Request) -> dict[str, str]:
    try:
        await request.app.state.redis.ping()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"redis unreachable: {exc}") from exc
    return {"status": "ready"}


@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


@app.post("/v1/workflows")
async def submit_workflow(
    request: Request,
    payload: dict,  # type: ignore[type-arg]
    principal: Principal = Depends(get_principal),
    settings: Settings = Depends(get_settings),
) -> Response:
    rate_limiter: RateLimiter = request.app.state.rate_limiter
    bucket = f"rl:{principal.tenant_id}"
    allowed, remaining = await rate_limiter.allow(bucket)
    if not allowed:
        return Response(
            content='{"error":"rate_limit_exceeded"}',
            media_type="application/json",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": "1", "X-RateLimit-Remaining": f"{remaining:.2f}"},
        )

    trace_id = request.state.trace_id
    with span(
        "gateway.submit_workflow",
        **{"tenant.id": principal.tenant_id, "trace_id": trace_id},
    ):
        client: httpx.AsyncClient = request.app.state.http_client
        try:
            upstream = await client.post(
                f"{settings.orchestrator_url}/v1/workflows",
                json=payload,
                headers={
                    "x-trace-id": trace_id,
                    "x-tenant-id": principal.tenant_id,
                    "x-subject": principal.subject,
                },
            )
        except httpx.RequestError as exc:
            log.error("gateway.upstream_unreachable", err=str(exc))
            raise HTTPException(status_code=503, detail="orchestrator unreachable") from exc

    return Response(
        content=upstream.content,
        media_type=upstream.headers.get("content-type", "application/json"),
        status_code=upstream.status_code,
        headers={"x-trace-id": trace_id, "X-RateLimit-Remaining": f"{remaining:.2f}"},
    )


@app.get("/v1/replay/{trace_id}")
async def replay(
    request: Request,
    trace_id: str,
    principal: Principal = Depends(get_principal),
    settings: Settings = Depends(get_settings),
) -> Response:
    client: httpx.AsyncClient = request.app.state.http_client
    upstream = await client.get(
        f"{settings.replay_url}/v1/replay/{trace_id}",
        headers={"x-tenant-id": principal.tenant_id},
    )
    return Response(
        content=upstream.content,
        media_type=upstream.headers.get("content-type", "application/json"),
        status_code=upstream.status_code,
    )
