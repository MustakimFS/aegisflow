"""Seed the memory service with sample documents for the demo workflow."""

from __future__ import annotations

import json
import sys
import time

import httpx
import jwt

MEMORY_URL = "http://localhost:8084"
GATEWAY_URL = "http://localhost:8080"
JWT_SECRET = "devonly_change_me"

DOCS = [
    {
        "text": (
            "Lattice-based cryptography is one of the leading approaches to post-quantum "
            "security. NIST has standardized CRYSTALS-Kyber for key encapsulation and "
            "CRYSTALS-Dilithium for digital signatures."
        ),
        "metadata": {"source": "nist-pqc-overview", "tag": "crypto"},
    },
    {
        "text": (
            "Migrating to post-quantum cryptography requires inventory of all systems using "
            "RSA, ECDSA, and DH key exchange. Hybrid schemes that combine classical and "
            "post-quantum primitives are common during the transition."
        ),
        "metadata": {"source": "pqc-migration-guide", "tag": "crypto"},
    },
    {
        "text": (
            "Hash-based signature schemes like SPHINCS+ provide an alternative with "
            "well-understood security assumptions, at the cost of larger signatures."
        ),
        "metadata": {"source": "sphincs-tradeoffs", "tag": "crypto"},
    },
]


def token() -> str:
    return jwt.encode(
        {
            "sub": "seeder",
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
    r = httpx.post(
        f"{MEMORY_URL}/v1/upsert",
        headers={"x-tenant-id": "demo"},
        json={"items": DOCS},
        timeout=10.0,
    )
    r.raise_for_status()
    print("seeded:", r.json())

    print("\nverifying with a workflow run:")
    res = httpx.post(
        f"{GATEWAY_URL}/v1/workflows",
        headers={"Authorization": f"Bearer {token()}"},
        json={
            "workflow": "research_summarize",
            "input": {"topic": "post-quantum cryptography migration"},
            "policies": {
                "max_retries": 2,
                "min_confidence": 0.5,
                "deadline_seconds": 15.0,
                "fallback_chain": ["mock", "rule_based_fallback"],
            },
        },
        timeout=30.0,
    )
    res.raise_for_status()
    print(json.dumps(res.json(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
