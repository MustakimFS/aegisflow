"""Routing decisions over reliability reports."""

from __future__ import annotations

from aegis_core.schemas import RecommendedAction, ReliabilityReport
from orchestrator.routing import decide


def _report(action: RecommendedAction, confidence: float = 0.8) -> ReliabilityReport:
    return ReliabilityReport(
        confidence=confidence,
        structural_valid=True,
        semantic_valid=True,
        grounded=True,
        refusal=False,
        anomaly_tags=[],
        recommended_action=action,
    )


def test_accept_short_circuits() -> None:
    d = decide(
        _report(RecommendedAction.ACCEPT),
        current_provider="openai",
        fallback_chain=["openai", "mock"],
        attempts_made=1,
        max_retries=3,
    )
    assert d.accept is True


def test_retry_within_budget() -> None:
    d = decide(
        _report(RecommendedAction.RETRY, confidence=0.6),
        current_provider="openai",
        fallback_chain=["openai", "mock"],
        attempts_made=1,
        max_retries=3,
    )
    assert d.retry_provider == "openai"


def test_retry_exhausted_advances_fallback() -> None:
    d = decide(
        _report(RecommendedAction.RETRY, confidence=0.6),
        current_provider="openai",
        fallback_chain=["openai", "mock"],
        attempts_made=3,
        max_retries=3,
    )
    assert d.fallback_provider == "mock"


def test_fallback_chain_exhausted_rejects() -> None:
    d = decide(
        _report(RecommendedAction.FALLBACK),
        current_provider="mock",
        fallback_chain=["openai", "mock"],
        attempts_made=1,
        max_retries=3,
    )
    assert d.accept is False
    assert d.reject_reason == "fallback chain exhausted"


def test_explicit_reject() -> None:
    d = decide(
        _report(RecommendedAction.REJECT),
        current_provider="openai",
        fallback_chain=["openai", "mock"],
        attempts_made=1,
        max_retries=3,
    )
    assert d.accept is False
    assert d.reject_reason
