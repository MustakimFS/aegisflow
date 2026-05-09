"""Composite confidence scoring tests."""

from __future__ import annotations

import math

from reliability.confidence import (
    Components,
    Weights,
    anomaly_penalty,
    grounding_score,
    historical_score,
    structural_score,
)


def test_structural_score_clean_json() -> None:
    assert structural_score('{"a": 1}') == 1.0


def test_structural_score_recoverable() -> None:
    assert structural_score('{"a": 1') == 0.5


def test_structural_score_unparseable() -> None:
    assert structural_score("just prose") == 0.0


def test_grounding_score_neutral_when_no_context() -> None:
    assert grounding_score("Some answer.", []) == 0.5


def test_grounding_score_high_overlap() -> None:
    text = "Lattice-based cryptography is a quantum-resistant approach. NIST has standardized Kyber for key encapsulation."
    retrieved = [
        {"text": "Lattice-based cryptography forms the basis of post-quantum schemes like Kyber, standardized by NIST."}
    ]
    score = grounding_score(text, retrieved)
    assert score >= 0.5


def test_grounding_score_low_overlap() -> None:
    text = "The capital of France is Paris."
    retrieved = [{"text": "Quantum cryptography deals with post-quantum algorithms."}]
    score = grounding_score(text, retrieved)
    assert score < 0.5


def test_historical_score_uses_prior_at_zero_samples() -> None:
    assert historical_score(0.0, 0) == 0.8


def test_historical_score_trusts_high_n() -> None:
    score = historical_score(success_rate=0.5, samples=1000)
    assert 0.50 <= score <= 0.55


def test_anomaly_penalty_diminishing() -> None:
    p1 = anomaly_penalty(1)
    p5 = anomaly_penalty(5)
    assert p5 < 5 * p1
    assert math.isclose(p1, 1 - math.exp(-0.5), rel_tol=1e-6)


def test_composite_clamped_to_unit_interval() -> None:
    c = Components(
        structural=1.0,
        grounding=1.0,
        critique=1.0,
        history=1.0,
        anomaly_penalty=10.0,  # extreme; would push composite negative
    )
    assert c.composite(Weights()) == 0.0

    c2 = Components(
        structural=1.0, grounding=1.0, critique=1.0, history=1.0, anomaly_penalty=0.0
    )
    assert c2.composite(Weights()) <= 1.0
