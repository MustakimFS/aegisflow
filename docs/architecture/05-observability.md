# 05 - Observability

> A code path without a trace span, a metric, and a structured log doesn't get merged.

## The three pillars (and how we wire each)

### Traces - OpenTelemetry → OTLP → Tempo

Every external request opens a root span at the gateway. Every internal hop
creates a child span. The trace ID flows in the `x-trace-id` header on
inbound HTTP, in the `traceparent` header on outbound HTTP, and is bound
into structlog contextvars so logs join cleanly.

Span attributes always include:

```
tenant.id, workflow.name, workflow.run_id, agent.id,
provider.name, provider.model, tokens.in, tokens.out,
reliability.confidence, retry.count, fallback.depth
```

### Metrics - Prometheus client → /metrics → Prometheus

We register metric families *once* in `aegis_core.metrics`. Services pass
labels at observation time. Family list:

```
aegisflow_workflow_duration_seconds{workflow,status}        # histogram
aegisflow_agent_invocations_total{agent,provider,outcome}   # counter
aegisflow_reliability_confidence{workflow}                  # histogram
aegisflow_circuit_state{provider,model}                     # gauge (0/1/2)
aegisflow_retries_total{provider,reason}                    # counter
aegisflow_fallback_total{from_provider,to_provider}         # counter
aegisflow_tokens_total{provider,direction}                  # counter
aegisflow_memory_recall_at_k{k}                             # histogram
aegisflow_chaos_injections_total{scenario}                  # counter
aegisflow_guardrail_violations_total{category}              # counter
aegisflow_hallucination_flags_total{workflow,heuristic}     # counter
```

### Logs - structlog (JSON) → stdout → log aggregator of choice

Every log line carries:

```
{
  "service": "orchestrator",
  "trace_id": "fa3b...",
  "span_id":  "9c2d...",
  "tenant_id": "demo",
  "workflow": "research_summarize",
  "level": "info",
  "event": "node_succeeded",
  "node_id": "execute",
  "confidence": 0.86,
  "ts": "2026-03-04T14:11:22Z"
}
```

Log fields are keys in the JSON object, not concatenated into the message.
Search and dashboarding work on top of any log aggregator - Loki, ELK,
Datadog, Splunk.

## SLOs

| Signal | SLO target | Measurement window |
| --- | --- | --- |
| Gateway availability | 99.9% | 30 days, rolling |
| p95 workflow latency | ≤ 3s | 7 days |
| Reliability rejection rate | ≤ 5% | 24h |
| Provider fallback rate | ≤ 10% | 24h |
| Replay event ingestion lag | ≤ 5s | 1h |

These are wired as Prometheus alert rules in `infra/observability/alerts.yml`
(TODO file). Breaching for ≥ 2 evaluation cycles pages the on-call rotation.

## Default Grafana dashboard

`infra/observability/grafana/dashboards/aegisflow-overview.json` ships a
single dashboard with eight panels:

1. Workflow throughput (RPS)
2. p95 workflow latency
3. Reliability rejection rate
4. Average confidence
5. Confidence distribution (p50, p95)
6. Retries / fallbacks per second
7. Circuit breaker state per provider/model
8. Hallucination flags per heuristic

This is the dashboard you should pull up first during an incident.

## What we deliberately do *not* observe

- **Per-prompt content in metrics.** Prompts can contain PII; aggregating
  them into metrics is a privacy hazard. They live in the replay log,
  which has access controls.
- **Synthetic confidence floors.** It's tempting to emit a `confidence_synthetic`
  metric that "fixes" missing scores by assuming 0.85. We don't - missing
  scores break dashboards in obvious ways, which is what we want.
- **Latency targets per individual provider.** Provider latency varies
  hugely; a per-provider SLO would be misleading. We track p95 *workflow*
  latency, since that's what the customer experiences.
