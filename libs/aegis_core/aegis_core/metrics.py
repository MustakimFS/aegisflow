"""Prometheus metric registry shared across services.

We register the metric *families* once on import. Services pass labels at
observation time. This avoids the common bug where a service crashes on
startup because the same metric was registered twice.
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

REGISTRY = CollectorRegistry(auto_describe=True)

WORKFLOW_DURATION = Histogram(
    "aegisflow_workflow_duration_seconds",
    "End-to-end workflow latency",
    labelnames=("workflow", "status"),
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0),
    registry=REGISTRY,
)

AGENT_INVOCATIONS = Counter(
    "aegisflow_agent_invocations_total",
    "Agent invocations by outcome",
    labelnames=("agent", "provider", "outcome"),
    registry=REGISTRY,
)

RELIABILITY_CONFIDENCE = Histogram(
    "aegisflow_reliability_confidence",
    "Composite confidence scores produced by the reliability engine",
    labelnames=("workflow",),
    buckets=(0.0, 0.1, 0.25, 0.5, 0.7, 0.8, 0.9, 0.95, 1.0),
    registry=REGISTRY,
)

CIRCUIT_STATE = Gauge(
    "aegisflow_circuit_state",
    "Circuit breaker state - 0=closed, 1=half_open, 2=open",
    labelnames=("provider", "model"),
    registry=REGISTRY,
)

RETRIES = Counter(
    "aegisflow_retries_total",
    "Retries by reason",
    labelnames=("provider", "reason"),
    registry=REGISTRY,
)

FALLBACKS = Counter(
    "aegisflow_fallback_total",
    "Provider fallbacks executed",
    labelnames=("from_provider", "to_provider"),
    registry=REGISTRY,
)

TOKENS = Counter(
    "aegisflow_tokens_total",
    "Tokens consumed by direction",
    labelnames=("provider", "direction"),
    registry=REGISTRY,
)

MEMORY_RECALL_AT_K = Histogram(
    "aegisflow_memory_recall_at_k",
    "Recall@k of the semantic memory service against ground truth",
    labelnames=("k",),
    buckets=(0.0, 0.25, 0.5, 0.75, 0.9, 1.0),
    registry=REGISTRY,
)

CHAOS_INJECTIONS = Counter(
    "aegisflow_chaos_injections_total",
    "Chaos injections executed by scenario name",
    labelnames=("scenario",),
    registry=REGISTRY,
)

GUARDRAIL_VIOLATIONS = Counter(
    "aegisflow_guardrail_violations_total",
    "Guardrail violations by category",
    labelnames=("category",),
    registry=REGISTRY,
)

HALLUCINATION_FLAGS = Counter(
    "aegisflow_hallucination_flags_total",
    "Outputs flagged by hallucination heuristics",
    labelnames=("workflow", "heuristic"),
    registry=REGISTRY,
)
