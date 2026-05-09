"""Output sanitization. Strip prompt-injection markers and obvious PII before returning."""

from __future__ import annotations

import re

# Conservative patterns. False positives are preferable to leaking data.
_PII_PATTERNS = (
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED:SSN]"),
    (
        re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
        "[REDACTED:CARD]",
    ),
    (
        re.compile(
            r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
        ),
        "[REDACTED:EMAIL]",
    ),
)

_INJECTION_MARKERS = (
    re.compile(r"ignore (all )?previous instructions", re.IGNORECASE),
    re.compile(r"<\|im_start\|>"),
    re.compile(r"BEGIN SYSTEM PROMPT", re.IGNORECASE),
)


def sanitize(text: str, *, redact_pii: bool = True) -> tuple[str, list[str]]:
    """Return sanitized text and a list of what we stripped."""
    actions: list[str] = []
    out = text

    for pattern in _INJECTION_MARKERS:
        if pattern.search(out):
            out = pattern.sub("[INJECTION_MARKER_REMOVED]", out)
            actions.append("stripped_injection_marker")

    if redact_pii:
        for pattern, replacement in _PII_PATTERNS:
            new = pattern.sub(replacement, out)
            if new != out:
                actions.append(f"redacted_{replacement.strip('[]:').lower()}")
                out = new

    return out, actions
