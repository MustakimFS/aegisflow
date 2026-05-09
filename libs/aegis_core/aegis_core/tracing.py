"""OpenTelemetry bootstrap shared across services.

Each service calls `init_tracing(service_name)` at startup. After that,
`tracer = get_tracer(__name__)` works as a drop-in for the OTel API.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span, Tracer

_initialized = False


def init_tracing(service_name: str) -> None:
    """Idempotent. Set up a global tracer provider that exports to OTLP gRPC."""
    global _initialized  # noqa: PLW0603
    if _initialized:
        return

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")
    resource = Resource.create(
        {
            "service.name": service_name,
            "service.namespace": "aegisflow",
            "deployment.environment": os.environ.get("ENV", "local"),
        }
    )

    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)

    _initialized = True


def get_tracer(name: str) -> Tracer:
    return trace.get_tracer(name)


@contextmanager
def span(name: str, **attributes: object) -> Iterator[Span]:
    """Convenience context manager that opens a span and tags it with attributes."""
    tracer = trace.get_tracer("aegis_core")
    with tracer.start_as_current_span(name) as s:
        for k, v in attributes.items():
            if v is not None:
                s.set_attribute(k, v)  # type: ignore[arg-type]
        yield s
