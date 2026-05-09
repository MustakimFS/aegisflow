"""Reliability engine output schema. The orchestrator consumes this to decide accept/retry/fallback."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class AnomalyTag(StrEnum):
    LENGTH_OUTLIER = "length_outlier"
    REPETITION = "repetition"
    REFUSAL = "refusal"
    HALLUCINATION_PATTERN = "hallucination_pattern"
    LOW_GROUNDING = "low_grounding"
    INJECTION_MARKER = "injection_marker"
    SCHEMA_FAILURE = "schema_failure"


class RecommendedAction(StrEnum):
    ACCEPT = "accept"
    RETRY = "retry"
    FALLBACK = "fallback"
    REJECT = "reject"


class ReliabilityReport(BaseModel):
    confidence: float = Field(ge=0.0, le=1.0)
    structural_valid: bool
    semantic_valid: bool
    grounded: bool
    refusal: bool
    anomaly_tags: list[AnomalyTag] = Field(default_factory=list)
    recommended_action: RecommendedAction
    component_scores: dict[str, float] = Field(default_factory=dict)
    rationale: str | None = None

    @classmethod
    def reject(cls, reason: str, anomalies: list[AnomalyTag] | None = None) -> ReliabilityReport:
        return cls(
            confidence=0.0,
            structural_valid=False,
            semantic_valid=False,
            grounded=False,
            refusal=False,
            anomaly_tags=anomalies or [],
            recommended_action=RecommendedAction.REJECT,
            rationale=reason,
        )
