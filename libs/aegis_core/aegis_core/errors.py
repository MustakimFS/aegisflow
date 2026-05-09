from __future__ import annotations


class AegisError(Exception):
    """Base for all AegisFlow exceptions. Carries a structured payload for tracing."""

    code: str = "aegis.error"

    def __init__(self, message: str, **context: object) -> None:
        super().__init__(message)
        self.message = message
        self.context = context

    def to_dict(self) -> dict[str, object]:
        return {"code": self.code, "message": self.message, **self.context}


class UpstreamTimeout(AegisError):
    code = "aegis.upstream_timeout"


class CircuitOpenError(AegisError):
    code = "aegis.circuit_open"


class ReliabilityRejection(AegisError):
    """Raised when reliability engine rejects an output past the policy threshold."""

    code = "aegis.reliability_rejection"


class GuardrailViolation(AegisError):
    """Raised when output fails schema, sanitization, or critique."""

    code = "aegis.guardrail_violation"


class ChaosInjection(AegisError):
    """Synthetic failure injected by the chaos engine. Counts as a failure to circuit breakers."""

    code = "aegis.chaos_injection"
