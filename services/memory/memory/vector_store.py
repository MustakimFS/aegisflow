"""pgvector-backed semantic store with cosine similarity ANN search."""

from __future__ import annotations

import json
from typing import Any

import asyncpg
import numpy as np


class VectorStore:
    def __init__(self, pool: asyncpg.Pool, dim: int = 384) -> None:
        self._pool = pool
        self._dim = dim

    async def upsert(
        self,
        tenant_id: str,
        items: list[dict[str, Any]],
        embeddings: np.ndarray,
    ) -> int:
        if embeddings.shape[0] != len(items):
            raise ValueError("embeddings/items length mismatch")
        records = [
            (
                tenant_id,
                item.get("namespace", "default"),
                item["text"],
                _vec_literal(embeddings[i]),
                item.get("metadata", {}),
            )
            for i, item in enumerate(items)
        ]
        async with self._pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO memory_chunks (tenant_id, namespace, text, embedding, metadata)
                VALUES ($1, $2, $3, $4::vector, $5::jsonb)
                """,
                [
                    (r[0], r[1], r[2], r[3], _json_dumps(r[4]))
                    for r in records
                ],
            )
        return len(items)

    async def search(
        self,
        tenant_id: str,
        query_embedding: np.ndarray,
        *,
        k: int = 5,
        namespace: str = "default",
    ) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, text, metadata,
                       1 - (embedding <=> $3::vector) AS similarity
                FROM memory_chunks
                WHERE tenant_id = $1 AND namespace = $2
                ORDER BY embedding <=> $3::vector
                LIMIT $4
                """,
                tenant_id,
                namespace,
                _vec_literal(query_embedding),
                k,
            )
        return [
            {
                "id": str(r["id"]),
                "text": r["text"],
                "metadata": _json_loads(r["metadata"]),
                "similarity": float(r["similarity"]),
            }
            for r in rows
        ]


def _vec_literal(vec: np.ndarray) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vec.tolist()) + "]"


def _json_dumps(obj: object) -> str:
    return json.dumps(obj)


def _json_loads(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}
    return {}
