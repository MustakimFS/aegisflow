# 01 - System Overview

AegisFlow is a microservices platform that turns probabilistic LLM calls into
deterministic, recoverable, auditable workflows. This document gives you the
30-minute tour.

## Mental model

If you've worked on a service mesh, the analogy is direct:

| Mesh concept | AegisFlow analogue |
| --- | --- |
| Sidecar proxy | Reliability + Guardrails + Replay middleware |
| Circuit breaker | Per-provider breaker in `aegis_core.circuit_breaker` |
| Retry policy | `aegis_core.retry.RetryPolicy`, deadline-aware |
| Distributed tracing | OpenTelemetry, end-to-end |
| Service registry | NATS subjects + k8s services |
| Failure injection | Chaos engine with HTTP scenario API |

The difference: in a service mesh, "success" is binary - the response either
arrived or it didn't. In AegisFlow, success is *scored*. A 200 response can
still be a hallucination, a malformed structure, or a refusal.

## Service responsibilities at a glance

```
┌─────────────────────────────────────────────────────────────┐
│ Gateway                                                     │
│   - JWT verification, tenant resolution                     │
│   - Token-bucket rate limiter (Redis Lua)                   │
│   - Trace ID minting & propagation                          │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│ Orchestrator                                                │
│   - Workflow DAG walker (topological)                       │
│   - Agent registry (planner / executor / validator / fb)    │
│   - Per-provider circuit breakers via aegis_core            │
│   - Routing decisions from Reliability reports              │
└──────┬─────────────┬────────────┬──────────┬────────────────┘
       │             │            │          │
       ▼             ▼            ▼          ▼
┌────────────┐ ┌────────────┐ ┌────────┐ ┌────────────┐
│Reliability │ │ Guardrails │ │ Memory │ │  Replay    │
│  scoring   │ │ schema/PII │ │  RAG   │ │ event log  │
└────────────┘ └────────────┘ └────────┘ └────────────┘
```

Each service is independently deployable, has its own circuit breaker boundary,
and emits `/metrics` + OTEL traces.

## Two control loops

There are *two* control loops in the system, and keeping them straight is
the key to understanding the architecture:

1. **Per-call loop** (millisecond scale)
   - circuit breaker → retry → timeout → score → guardrail → accept/fallback
   - lives entirely inside `orchestrator.engine.Engine._run_node`

2. **Workflow loop** (seconds scale)
   - DAG walker → next node → memory retrieval → agent dispatch
   - lives in `orchestrator.engine.Engine.execute`

The per-call loop is where the reliability magic happens. The workflow loop
is mostly a topological sort with bookkeeping.

## Why microservices?

A monolith would be 30% less code. Three reasons we still went distributed:

1. **Independent failure domains**: the reliability engine being CPU-bound
   shouldn't drag down the I/O-bound memory service.
2. **Independent scaling axes**: token-heavy workloads scale orchestrator
   replicas; rerank-heavy workloads scale memory replicas.
3. **Provable isolation for chaos testing**: we can take down `reliability`
   and observe the orchestrator gracefully degrading to "fail closed".

## What's *not* in this diagram

- **Tenant management**: the gateway expects upstream JWTs from your IDP. We
  don't run identity.
- **Secrets**: `aegisflow-secrets` k8s manifest is a stub. Real deployments
  source from AWS Secrets Manager / Vault via External Secrets Operator.
- **Multi-region**: `infra/k8s/overlays/prod` is single-region. Multi-region
  is on the roadmap and will use NATS leaf nodes.
