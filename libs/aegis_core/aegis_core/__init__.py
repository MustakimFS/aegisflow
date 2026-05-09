"""AegisFlow shared primitives."""

from aegis_core.circuit_breaker import CircuitBreaker, CircuitState
from aegis_core.errors import (
    AegisError,
    CircuitOpenError,
    GuardrailViolation,
    ReliabilityRejection,
    UpstreamTimeout,
)
from aegis_core.ids import new_run_id, new_span_id, new_trace_id
from aegis_core.retry import RetryPolicy, retry_async
from aegis_core.timeout import deadline_budget, with_timeout

__all__ = [
    "AegisError",
    "CircuitBreaker",
    "CircuitOpenError",
    "CircuitState",
    "GuardrailViolation",
    "ReliabilityRejection",
    "RetryPolicy",
    "UpstreamTimeout",
    "deadline_budget",
    "new_run_id",
    "new_span_id",
    "new_trace_id",
    "retry_async",
    "with_timeout",
]
