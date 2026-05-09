"""End-to-end smoke test against `docker compose up`. Marked `integration`."""

from __future__ import annotations

import os
import time

import httpx
import jwt
import pytest

GATEWAY = os.environ.get("AEGIS_GATEWAY_URL", "http://localhost:8080")
JWT_SECRET = os.environ.get("JWT_SECRET", "devonly_change_me")


pytestmark = pytest.mark.integration


def _token(tenant_id: str = "demo", subject: str = "tester") -> str:
    return jwt.encode(
        {
            "sub": subject,
            "tenant_id": tenant_id,
            "iss": "aegisflow.local",
            "aud": "aegisflow.api",
            "iat": int(time.time()),
            "exp": int(time.time()) + 600,
            "scopes": ["workflows:run"],
        },
        JWT_SECRET,
        algorithm="HS256",
    )


def test_health_endpoints_all_respond() -> None:
    for path in ("/healthz",):
        r = httpx.get(f"{GATEWAY}{path}", timeout=5.0)
        assert r.status_code == 200


def test_workflow_succeeds_end_to_end() -> None:
    r = httpx.post(
        f"{GATEWAY}/v1/workflows",
        headers={"Authorization": f"Bearer {_token()}"},
        json={
            "workflow": "research_summarize",
            "input": {"topic": "post-quantum cryptography"},
            "policies": {
                "max_retries": 2,
                "min_confidence": 0.5,
                "deadline_seconds": 15.0,
                "fallback_chain": ["mock", "rule_based_fallback"],
            },
        },
        timeout=30.0,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] in {"succeeded"}
    assert "trace_id" in body
    assert "run_id" in body


def test_unauthorized_request_rejected() -> None:
    r = httpx.post(
        f"{GATEWAY}/v1/workflows",
        json={"workflow": "research_summarize", "input": {"topic": "x"}},
        timeout=5.0,
    )
    assert r.status_code == 401


def test_replay_returns_event_log() -> None:
    submit = httpx.post(
        f"{GATEWAY}/v1/workflows",
        headers={"Authorization": f"Bearer {_token()}"},
        json={
            "workflow": "classify",
            "input": {"topic": "auth-related ticket"},
            "policies": {
                "max_retries": 1,
                "min_confidence": 0.5,
                "deadline_seconds": 10.0,
                "fallback_chain": ["mock", "rule_based_fallback"],
            },
        },
        timeout=20.0,
    )
    assert submit.status_code == 200
    trace_id = submit.json()["trace_id"]

    # Give replay a moment to receive async events
    time.sleep(0.5)

    r = httpx.get(
        f"{GATEWAY}/v1/replay/{trace_id}",
        headers={"Authorization": f"Bearer {_token()}"},
        timeout=10.0,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["count"] >= 1
    assert body["trace_id"] == trace_id
