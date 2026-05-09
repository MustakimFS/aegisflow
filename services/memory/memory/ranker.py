"""Cheap reranker that boosts recency + lexical overlap on top of vector similarity.

A real deployment would call a cross-encoder reranker. For the demo we use a
simple linear combination - explainable and fast.
"""

from __future__ import annotations

import math
import re
import time
from typing import Any

_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN.findall(text.lower()) if len(t) >= 3}


def rerank(
    query: str,
    hits: list[dict[str, Any]],
    *,
    similarity_weight: float = 0.7,
    lexical_weight: float = 0.2,
    recency_weight: float = 0.1,
) -> list[dict[str, Any]]:
    if not hits:
        return hits
    q_tokens = _tokens(query)
    now = time.time()
    scored: list[tuple[float, dict[str, Any]]] = []
    for h in hits:
        sim = float(h.get("similarity", 0.0))
        h_tokens = _tokens(h.get("text", ""))
        lex = (
            len(q_tokens & h_tokens) / max(1, len(q_tokens | h_tokens))
            if q_tokens
            else 0.0
        )
        ts = h.get("metadata", {}).get("created_at_ts")
        recency = math.exp(-((now - ts) / 86400.0)) if isinstance(ts, (int, float)) else 0.0
        score = similarity_weight * sim + lexical_weight * lex + recency_weight * recency
        scored.append((score, {**h, "rerank_score": score}))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [h for _, h in scored]
