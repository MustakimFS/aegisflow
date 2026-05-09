"""Top-level scoring pipeline. Combines heuristics + composite confidence into a report."""

from __future__ import annotations

from aegis_core.metrics import HALLUCINATION_FLAGS
from aegis_core.schemas import (
    AgentInvocation,
    AgentOutput,
    AnomalyTag,
    Policies,
    RecommendedAction,
    ReliabilityReport,
)

from reliability.confidence import (
    Components,
    Weights,
    anomaly_penalty,
    critique_score,
    grounding_score,
    historical_score,
    structural_score,
)
from reliability.hallucination import collect_anomalies, detect_refusal


class ProviderHistory:
    """Rolling 5-minute success-rate cache. In-process - sharded by provider."""

    def __init__(self) -> None:
        self._success: dict[str, int] = {}
        self._total: dict[str, int] = {}

    def observe(self, provider: str, ok: bool) -> None:
        self._total[provider] = self._total.get(provider, 0) + 1
        if ok:
            self._success[provider] = self._success.get(provider, 0) + 1

    def stats(self, provider: str) -> tuple[float, int]:
        total = self._total.get(provider, 0)
        if total == 0:
            return 0.8, 0  # prior
        return self._success.get(provider, 0) / total, total


def score(
    *,
    workflow: str,
    invocation: AgentInvocation,
    output: AgentOutput,
    policies: Policies,
    history: ProviderHistory,
    weights: Weights = Weights(),
) -> ReliabilityReport:
    refusal = detect_refusal(output.raw_text)
    structural = structural_score(output.raw_text)
    grounding = grounding_score(output.raw_text, invocation.retrieved_context)
    grounded = grounding >= 0.5

    critique_payload = (output.parsed or {}).get("validator_critique") if output.parsed else None
    critique = critique_score(critique_payload)

    success_rate, samples = history.stats(invocation.provider)
    history_score = historical_score(success_rate, samples)

    anomalies = collect_anomalies(
        text=output.raw_text,
        tokens_out=output.tokens_out,
        grounded=grounded,
    )
    if structural < 1.0:
        anomalies.append(AnomalyTag.SCHEMA_FAILURE)

    components = Components(
        structural=structural,
        grounding=grounding,
        critique=critique,
        history=history_score,
        anomaly_penalty=anomaly_penalty(len(anomalies)),
    )
    confidence = components.composite(weights)

    if AnomalyTag.HALLUCINATION_PATTERN in anomalies:
        HALLUCINATION_FLAGS.labels(workflow, "phrasing").inc()
    if AnomalyTag.LOW_GROUNDING in anomalies:
        HALLUCINATION_FLAGS.labels(workflow, "low_grounding").inc()

    action = _decide_action(
        confidence=confidence,
        refusal=refusal,
        anomalies=anomalies,
        policies=policies,
    )

    return ReliabilityReport(
        confidence=confidence,
        structural_valid=structural >= 1.0,
        semantic_valid=grounding >= 0.5 and critique >= 0.5,
        grounded=grounded,
        refusal=refusal,
        anomaly_tags=anomalies,
        recommended_action=action,
        component_scores={
            "structural": structural,
            "grounding": grounding,
            "critique": critique,
            "history": history_score,
            "anomaly_penalty": components.anomaly_penalty,
        },
        rationale=_rationale(confidence, anomalies, refusal),
    )


def _decide_action(
    *,
    confidence: float,
    refusal: bool,
    anomalies: list[AnomalyTag],
    policies: Policies,
) -> RecommendedAction:
    if AnomalyTag.INJECTION_MARKER in anomalies:
        return RecommendedAction.REJECT
    if refusal:
        return RecommendedAction.FALLBACK
    if confidence >= policies.min_confidence:
        return RecommendedAction.ACCEPT
    if AnomalyTag.SCHEMA_FAILURE in anomalies and confidence >= policies.min_confidence - 0.1:
        return RecommendedAction.RETRY  # repair via guardrails on retry
    if confidence >= policies.min_confidence - 0.2:
        return RecommendedAction.RETRY
    return RecommendedAction.FALLBACK


def _rationale(confidence: float, anomalies: list[AnomalyTag], refusal: bool) -> str:
    if refusal:
        return "model refused; advancing fallback chain"
    if AnomalyTag.INJECTION_MARKER in anomalies:
        return "prompt-injection marker detected in output"
    if not anomalies:
        return f"clean output, confidence {confidence:.2f}"
    return f"confidence {confidence:.2f}; anomalies: {', '.join(a.value for a in anomalies)}"
