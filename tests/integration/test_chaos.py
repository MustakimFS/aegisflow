"""Verify the chaos engine actually exercises the fallback path."""

from __future__ import annotations

import os
import time

import httpx
import jwt
import pytest

GATEWAY = os.environ.get("AEGIS_GATEWAY_URL", "http://localhost:8080")
CHAOS = os.environ.get("AEGIS_CHAOS_URL", "http://localhost:8086")
JWT_SECRET = os.environ.get("JWT_SECRET", "devonly_change_me")

pytestmark = pytest.mark.integration


def _token() -> str:
    return jwt.encode(
        {
            "sub": "chaos-tester",
            "tenant_id": "demo",
            "iss": "aegisflow.local",
            "aud": "aegisflow.api",
            "iat": int(time.time()),
            "exp": int(time.time()) + 600,
        },
        JWT_SECRET,
        algorithm="HS256",
    )


def test_fallback_chain_engages_under_chaos() -> None:
    # Enable JSON corruption scenario
    httpx.post(f"{CHAOS}/v1/chaos/scenarios/json-corruption/enable", timeout=5.0)
    try:
        observed_fallbacks = 0
        for _ in range(8):
            r = httpx.post(
                f"{GATEWAY}/v1/workflows",
                headers={"Authorization": f"Bearer {_token()}"},
                json={
                    "workflow": "classify",
                    "input": {"topic": "cardinality"},
                    "policies": {
                        "max_retries": 1,
                        "min_confidence": 0.6,
                        "deadline_seconds": 8.0,
                        "fallback_chain": ["mock", "rule_based_fallback"],
                    },
                },
                timeout=15.0,
            )
            assert r.status_code == 200
            body = r.json()
            if body.get("fallback_depth", 0) > 0:
                observed_fallbacks += 1
        # At least one of the eight runs should have engaged the fallback chain.
        assert observed_fallbacks >= 1
    finally:
        httpx.post(f"{CHAOS}/v1/chaos/scenarios/json-corruption/disable", timeout=5.0)
