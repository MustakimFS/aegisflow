"""Fallback routing logic.

Given the reliability engine's recommended action, the orchestrator must
choose what to do *next*. This module isolates that policy so the engine
itself stays advisory.
"""

from __future__ import annotations

from dataclasses import dataclass

from aegis_core.schemas import RecommendedAction, ReliabilityReport


@dataclass
class RouteDecision:
    """What the orchestrator should do with this output."""

    accept: bool
    retry_provider: str | None = None
    fallback_provider: str | None = None
    reject_reason: str | None = None


def decide(
    report: ReliabilityReport,
    *,
    current_provider: str,
    fallback_chain: list[str],
    attempts_made: int,
    max_retries: int,
) -> RouteDecision:
    """Translate a reliability report into a concrete next action.

    Policy:
      - ACCEPT  → accept.
      - RETRY   → retry same provider while attempts remain; otherwise fallback.
      - FALLBACK→ advance the fallback chain; if exhausted, reject.
      - REJECT  → reject with the rationale.
    """
    if report.recommended_action is RecommendedAction.ACCEPT:
        return RouteDecision(accept=True)

    if report.recommended_action is RecommendedAction.REJECT:
        return RouteDecision(accept=False, reject_reason=report.rationale or "rejected")

    if report.recommended_action is RecommendedAction.RETRY and attempts_made < max_retries:
        return RouteDecision(accept=False, retry_provider=current_provider)
        # exhausted retries → fall through to fallback
    next_provider = _next_in_chain(current_provider, fallback_chain)
    if next_provider is None:
        return RouteDecision(accept=False, reject_reason="fallback chain exhausted")
    return RouteDecision(accept=False, fallback_provider=next_provider)


def _next_in_chain(current: str, chain: list[str]) -> str | None:
    try:
        idx = chain.index(current)
    except ValueError:
        return chain[0] if chain else None
    return chain[idx + 1] if idx + 1 < len(chain) else None
