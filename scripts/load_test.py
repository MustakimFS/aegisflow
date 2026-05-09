"""Tiny async load generator. Useful for watching the Grafana dashboards light up."""

from __future__ import annotations

import argparse
import asyncio
import json
import time

import httpx
import jwt

GATEWAY_URL = "http://localhost:8080"
JWT_SECRET = "devonly_change_me"


def token() -> str:
    return jwt.encode(
        {
            "sub": "load-tester",
            "tenant_id": "demo",
            "iss": "aegisflow.local",
            "aud": "aegisflow.api",
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        },
        JWT_SECRET,
        algorithm="HS256",
    )


async def fire(client: httpx.AsyncClient, sem: asyncio.Semaphore) -> int:
    async with sem:
        try:
            r = await client.post(
                f"{GATEWAY_URL}/v1/workflows",
                headers={"Authorization": f"Bearer {token()}"},
                json={
                    "workflow": "classify",
                    "input": {"topic": "auth"},
                    "policies": {
                        "max_retries": 1,
                        "min_confidence": 0.5,
                        "deadline_seconds": 8.0,
                        "fallback_chain": ["mock", "rule_based_fallback"],
                    },
                },
                timeout=15.0,
            )
            return r.status_code
        except httpx.HTTPError:
            return 0


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rps", type=int, default=10)
    parser.add_argument("--seconds", type=int, default=30)
    args = parser.parse_args()

    statuses: list[int] = []
    sem = asyncio.Semaphore(args.rps * 2)
    deadline = time.monotonic() + args.seconds
    async with httpx.AsyncClient() as client:
        tasks: list[asyncio.Task[int]] = []
        next_tick = time.monotonic()
        while time.monotonic() < deadline:
            for _ in range(args.rps):
                tasks.append(asyncio.create_task(fire(client, sem)))
            next_tick += 1.0
            await asyncio.sleep(max(0.0, next_tick - time.monotonic()))
        statuses = await asyncio.gather(*tasks)

    by_status: dict[int, int] = {}
    for s in statuses:
        by_status[s] = by_status.get(s, 0) + 1
    print(json.dumps({"sent": len(statuses), "by_status": by_status}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
