"""Heuristics for detecting common hallucination / failure patterns.

Heuristics here are intentionally cheap and explainable. They are *not* a
substitute for a critique pass - they catch the obvious failures (refusals,
length anomalies, repetition loops, prompt-injection echoes) before we
spend tokens on semantic critique.
"""

from __future__ import annotations

import re
from collections import Counter

from aegis_core.schemas import AnomalyTag

# Common refusal phrases. We don't want to retry these - the model has decided.
_REFUSAL_PATTERNS = (
    re.compile(r"\bI (cannot|can't|won't|am unable to)\b", re.IGNORECASE),
    re.compile(r"\bAs an AI\b", re.IGNORECASE),
    re.compile(r"\bI'm sorry,? but\b", re.IGNORECASE),
)

# Markers that indicate the model is echoing a prompt-injection attempt.
_INJECTION_PATTERNS = (
    re.compile(r"ignore (all )?previous instructions", re.IGNORECASE),
    re.compile(r"system:\s*you are", re.IGNORECASE),
    re.compile(r"<\|im_start\|>"),
    re.compile(r"BEGIN SYSTEM PROMPT", re.IGNORECASE),
)

# Phrases LLMs say when fabricating with low grounding.
_HALLUCINATION_HINTS = (
    re.compile(r"\bAccording to (my knowledge|recent studies|some sources)\b", re.IGNORECASE),
    re.compile(r"\bIt is widely (known|believed|reported)\b", re.IGNORECASE),
    re.compile(r"\bExperts generally agree\b", re.IGNORECASE),
)


def detect_refusal(text: str) -> bool:
    return any(p.search(text) for p in _REFUSAL_PATTERNS)


def detect_injection(text: str) -> bool:
    return any(p.search(text) for p in _INJECTION_PATTERNS)


def detect_hallucination_phrasing(text: str) -> bool:
    """Phrases LLMs lean on when ungrounded."""
    return any(p.search(text) for p in _HALLUCINATION_HINTS)


def detect_repetition(text: str, *, n: int = 3, threshold: float = 0.4) -> bool:
    """Look for repeated n-grams. High repetition correlates with degenerate decoding."""
    tokens = re.findall(r"\w+", text.lower())
    if len(tokens) < n * 4:
        return False
    grams = [" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]
    if not grams:
        return False
    counts = Counter(grams)
    most_common, freq = counts.most_common(1)[0]
    del most_common
    return freq / len(grams) >= threshold


def detect_length_outlier(
    *,
    tokens_out: int,
    typical_min: int = 8,
    typical_max: int = 4096,
) -> bool:
    return tokens_out < typical_min or tokens_out > typical_max


def collect_anomalies(
    *,
    text: str,
    tokens_out: int,
    grounded: bool,
) -> list[AnomalyTag]:
    tags: list[AnomalyTag] = []
    if detect_refusal(text):
        tags.append(AnomalyTag.REFUSAL)
    if detect_injection(text):
        tags.append(AnomalyTag.INJECTION_MARKER)
    if detect_hallucination_phrasing(text):
        tags.append(AnomalyTag.HALLUCINATION_PATTERN)
    if detect_repetition(text):
        tags.append(AnomalyTag.REPETITION)
    if detect_length_outlier(tokens_out=tokens_out):
        tags.append(AnomalyTag.LENGTH_OUTLIER)
    if not grounded:
        tags.append(AnomalyTag.LOW_GROUNDING)
    return tags
