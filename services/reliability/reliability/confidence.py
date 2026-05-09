"""Composite confidence scoring.

confidence = w_struct  * structural_score
           + w_ground  * grounding_score
           + w_critic  * critique_score
           + w_history * historical_provider_score
           - w_anom    * anomaly_penalty
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Weights:
    structural: float = 0.30
    grounding: float = 0.30
    critique: float = 0.20
    history: float = 0.10
    anomaly: float = 0.30  # subtracted, capped


@dataclass(frozen=True)
class Components:
    structural: float
    grounding: float
    critique: float
    history: float
    anomaly_penalty: float

    def composite(self, w: Weights) -> float:
        raw = (
            w.structural * self.structural
            + w.grounding * self.grounding
            + w.critique * self.critique
            + w.history * self.history
            - w.anomaly * self.anomaly_penalty
        )
        return max(0.0, min(1.0, raw))


def structural_score(raw: str) -> float:
    """1.0 = clean JSON, 0.5 = recoverable, 0.0 = unparseable."""
    try:
        json.loads(raw)
        return 1.0
    except json.JSONDecodeError:
        # cheap repairability check: balanced braces?
        opens = raw.count("{")
        closes = raw.count("}")
        if opens > 0 and abs(opens - closes) <= 1:
            return 0.5
        return 0.0


def grounding_score(text: str, retrieved: list[dict]) -> float:
    """Fraction of factual claims that overlap with retrieved context.

    A "claim" is approximated by a sentence containing a noun-phrase signal.
    Overlap is approximated by token Jaccard against the union of retrieved
    docs. This is a *fast proxy* for embedding-based grounding; the memory
    service does the more expensive cosine-similarity grounding when called.
    """
    if not retrieved:
        return 0.5  # neutral - we can't tell without context
    sentences = re.split(r"(?<=[.!?])\s+", text)
    if not sentences:
        return 0.5
    corpus_tokens = set()
    for r in retrieved:
        corpus_tokens.update(_tokens(r.get("text", "")))
    if not corpus_tokens:
        return 0.5

    grounded = 0
    counted = 0
    for s in sentences:
        s_tokens = _tokens(s)
        if len(s_tokens) < 4:
            continue
        counted += 1
        overlap = len(s_tokens & corpus_tokens) / max(1, len(s_tokens))
        if overlap >= 0.25:
            grounded += 1

    if counted == 0:
        return 0.5
    return grounded / counted


def critique_score(critique_payload: dict | None) -> float:
    """Validator-agent rubric score, averaged across axes. None → neutral 0.6."""
    if not critique_payload:
        return 0.6
    axes = ["groundedness", "structural", "relevance"]
    vals = [float(critique_payload.get(a, 0.6)) for a in axes if a in critique_payload]
    if not vals:
        return 0.6
    return sum(vals) / len(vals)


def historical_score(success_rate: float, samples: int) -> float:
    """Bayesian shrinkage toward 0.8 when sample size is small.

    With n=0 samples we return the prior. With n=200 we trust the rate fully.
    """
    prior = 0.8
    weight = samples / (samples + 50)
    return weight * success_rate + (1 - weight) * prior


def anomaly_penalty(num_anomalies: int) -> float:
    """Diminishing-returns penalty so 5 anomalies isn't 5x as bad as 1."""
    return 1 - math.exp(-0.5 * num_anomalies)


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) >= 3}
