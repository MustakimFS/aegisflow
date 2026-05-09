"""End-to-end demo: submit a workflow, dump the trace, fetch the replay log."""

from __future__ import annotations

import json
import sys
import time

import httpx
import jwt

GATEWAY_URL = "http://localhost:8080"
JWT_SECRET = "devonly_change_me"


def token() -> str:
    return jwt.encode(
        {
            "sub": "demo-runner",
            "tenant_id": "demo",
            "iss": "aegisflow.local",
            "aud": "aegisflow.api",
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        },
        JWT_SECRET,
        algorithm="HS256",
    )


def main() -> int:
    h = {"Authorization": f"Bearer {token()}"}
    res = httpx.post(
        f"{GATEWAY_URL}/v1/workflows",
        headers=h,
        json={
            "workflow": "research_summarize",
            "input": {"topic": "post-quantum cryptography migration"},
            "policies": {
                "max_retries": 2,
                "min_confidence": 0.6,
                "deadline_seconds": 15.0,
                "fallback_chain": ["mock", "rule_based_fallback"],
            },
        },
        timeout=30.0,
    )
    res.raise_for_status()
    body = res.json()
    print("=== Workflow result ===")
    print(json.dumps(body, indent=2))

    trace_id = body["trace_id"]
    time.sleep(0.5)
    rep = httpx.get(f"{GATEWAY_URL}/v1/replay/{trace_id}", headers=h, timeout=10.0)
    if rep.status_code == 200:
        print("\n=== Replay log ===")
        print(json.dumps(rep.json(), indent=2))
    else:
        print(f"\nReplay fetch returned {rep.status_code}: {rep.text}")

    print("\nGrafana dashboard: http://localhost:3000  (admin / admin)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
