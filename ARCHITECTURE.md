# AegisFlow - Architecture

This document describes the system in enough depth that a senior engineer joining the team could navigate the codebase, understand the failure modes, and reason about the trade-offs we made.

## 1. Goals and non-goals

### Goals

- **Determinism** on top of probabilistic systems. Every run is reproducible from its event log.
- **Resilience** against the specific failure modes of LLM systems: malformed outputs, hallucinations, provider outages, latency cliffs.
- **Observability-first**: every signal a senior on-call wants - token spend, retry rate, fallback rate, hallucination rate, cache hit rate, queue depth - is exported as a metric, span, or log.
- **Horizontal scalability** of the compute path. Storage scales separately.

### Non-goals

- We are not a model provider. AegisFlow wraps OpenAI, Anthropic, vLLM, local models - it doesn't ship one.
- We are not a UI for chat. We are infrastructure under your application.
- We do not optimize for raw latency at any cost. We optimize for *predictable* latency with explicit reliability guarantees.

## 2. System decomposition

AegisFlow is a microservices platform. Services communicate through two channels:

- **Synchronous gRPC / HTTP** for request-path interactions inside a single workflow.
- **Asynchronous NATS JetStream** for fan-out, audit, replay, chaos triggers, and cross-cutting events.

| Service | Process model | Persistence | Scaling axis |
| --- | --- | --- | --- |
| `gateway` | stateless · async | Redis (rate-limit) | request rate |
| `orchestrator` | stateless · async | Postgres (workflow runs) · NATS | concurrent workflows |
| `reliability` | stateless · CPU-bound | - (in-memory windows) | scoring throughput |
| `guardrails` | stateless · CPU-bound | - | validation throughput |
| `memory` | stateful read replicas | Postgres + pgvector · S3 | retrieval QPS |
| `replay` | stateful append-only | Postgres (event store) · S3 | event ingestion |
| `chaos` | stateless | Redis (active scenarios) | - |

Every service exposes:
- `/healthz` (liveness), `/readyz` (readiness), `/metrics` (Prometheus).
- OpenTelemetry trace export to the collector at `otel-collector:4317`.
- Structured JSON logs with `trace_id`, `workflow_id`, `agent_id`, `service`.

## 3. Data flow - happy path

```
1. Client → Gateway
   - JWT validated, tenant resolved, rate-limit checked against Redis token bucket.
   - Trace ID minted, root span opened, request forwarded to orchestrator.

2. Gateway → Orchestrator
   - Workflow definition resolved (DAG of agent nodes).
   - Run record persisted (Postgres) in state PENDING.
   - First node enqueued onto NATS subject `workflow.{id}.next`.

3. Orchestrator → Memory
   - Pre-task retrieval: query semantic memory for relevant context.
   - Top-k results reranked, attached to agent context envelope.

4. Orchestrator → LLM provider
   - Outbound call wrapped by:
     · per-provider circuit breaker (sliding window failure ratio),
     · adaptive retry with full jitter,
     · timeout budget allocated from workflow deadline.

5. Orchestrator → Reliability engine
   - Output scored: structural validity, semantic plausibility,
     ungrounded-claim detection, refusal detection, length anomaly.
   - Returns confidence ∈ [0,1] + categorized failure tags.

6. Orchestrator → Guardrails
   - JSON repair pass if structural failure detected.
   - Schema validation against declared output contract.
   - Sanitization (PII, prompt-injection markers, unsafe content).

7. Orchestrator decision
   - If confidence ≥ threshold → commit, advance DAG.
   - Else → consult fallback chain:
     a) retry same provider with adjusted parameters,
     b) failover to secondary provider,
     c) deterministic rule-based fallback,
     d) controlled failure with structured error.

8. Orchestrator → Replay
   - All inputs, outputs, scores, retries, decisions appended to event log.

9. Orchestrator → Client (via Gateway)
   - Final response with trace ID, confidence, and per-stage telemetry.
```

## 4. Reliability engine - the core innovation

The reliability engine treats every agent invocation as a probabilistic operation and produces a structured `ReliabilityReport`:

```python
class ReliabilityReport:
    confidence: float           # 0..1, calibrated
    structural_valid: bool      # JSON / schema parse succeeded
    semantic_valid: bool        # passed critique pass
    grounded: bool              # claims supported by retrieved context
    refusal: bool               # model declined
    anomaly_tags: list[str]     # 'length_outlier', 'repetition', 'hallucination_pattern'
    recommended_action: Literal['accept','retry','fallback','reject']
```

### How confidence is computed

Confidence is **not** the model's self-reported logprob. It is a composite score:

```
confidence = w1 * structural_score
           + w2 * grounding_score
           + w3 * critique_score
           + w4 * historical_provider_score
           - w5 * anomaly_penalty
```

- `structural_score`: passes JSON schema → 1.0; repairable → 0.5; unrepairable → 0.
- `grounding_score`: fraction of factual claims that appear in retrieved context (via embedding similarity ≥ τ).
- `critique_score`: secondary model rates the output on a fixed rubric. Cached aggressively.
- `historical_provider_score`: rolling 5-minute success rate for the provider on this workflow.
- `anomaly_penalty`: length / repetition / refusal markers.

Weights are workflow-configurable. Defaults are tuned on a held-out reliability benchmark and documented in `docs/architecture/03-reliability.md`.

### Fallback routing

The reliability engine doesn't *take* the action - it recommends. The orchestrator owns the policy. This separation matters: the same low-confidence output should retry on a research workflow but reject outright on a financial one.

## 5. Failure handling

### Circuit breakers

Per-provider, per-model. State transitions:

```
CLOSED ──(failure_ratio > threshold over window)──► OPEN
OPEN ──(cooldown elapsed)──► HALF_OPEN
HALF_OPEN ──(probe success)──► CLOSED
HALF_OPEN ──(probe failure)──► OPEN (extended cooldown)
```

Implemented in `libs/aegis_core/circuit_breaker.py`. Failure is defined narrowly - 5xx, timeout, connection error. Low-confidence outputs are *not* failures at this layer; they're handled by the reliability engine.

### Retries

Exponential backoff with full jitter (`base * 2^attempt * random()`), bounded by the remaining workflow deadline. Idempotency keys (workflow_id + node_id + attempt) prevent duplicate side effects.

### Timeouts

Workflow-level deadline propagates as a budget. Each node receives `min(node_timeout, remaining_budget)`. Soft-timeout cancels gracefully via `asyncio.CancelledError`; hard-timeout fires after grace period.

### Backpressure

NATS JetStream consumer groups have bounded `max_ack_pending`. When breached, the gateway returns 429 with `Retry-After` rather than letting queues grow unbounded.

## 6. Storage model

| Store | Used for | Why |
| --- | --- | --- |
| Postgres | workflow runs, replay event log, memory metadata | strong consistency, JSON columns, mature ops |
| pgvector | semantic memory embeddings | colocated with metadata, single-store retrieval |
| Redis | rate-limit counters, chaos active scenarios, hot cache | sub-ms latency, TTL primitives |
| NATS JetStream | event bus, replay buffer, async fan-out | at-least-once with ack, replayable |
| S3 | large payloads (raw model outputs > 32KB), exports | cheap durable blob |

## 7. Observability

Every external request creates a trace with this skeleton:

```
gateway.request
  └── orchestrator.workflow_run
        ├── memory.retrieve
        ├── llm.invoke (provider="openai", model="gpt-4o")
        ├── reliability.score
        ├── guardrails.validate
        └── replay.append
```

Span attributes always include: `tenant_id`, `workflow_id`, `agent_id`, `provider`, `model`, `tokens_in`, `tokens_out`, `confidence`, `retry_count`, `fallback_depth`.

Prometheus metric families:

```
aegisflow_workflow_duration_seconds{workflow,status}      # histogram
aegisflow_agent_invocations_total{agent,provider,outcome} # counter
aegisflow_reliability_confidence{workflow}                # histogram
aegisflow_circuit_state{provider,model}                   # gauge (0/1/2)
aegisflow_retries_total{provider,reason}                  # counter
aegisflow_fallback_total{from_provider,to_provider}       # counter
aegisflow_tokens_total{provider,direction}                # counter
aegisflow_memory_recall_at_k{k}                           # histogram
aegisflow_chaos_injections_total{scenario}                # counter
```

Default Grafana dashboard ships in `infra/observability/grafana/`.

## 8. Security model

- **Authentication**: JWT at the gateway, validated against tenant key rotation.
- **Authorization**: workflow definitions carry an ACL; orchestrator enforces before execution.
- **Tenant isolation**: every Postgres query is scoped by `tenant_id` (row-level security policies enforced).
- **Prompt-injection defense**: guardrails service detects and strips known injection markers from retrieved memory before passing to executor agents.
- **Secrets**: provider API keys live in the secret store (`AWS_SECRETS_MANAGER` in prod, `.env` locally), never in workflow configs.

## 9. Deployment

- **Local**: `docker compose up` brings up the full stack, including OTEL collector, Prometheus, Grafana, NATS, Postgres, Redis.
- **Kubernetes**: `infra/k8s/base` is a Kustomize base; `overlays/dev` and `overlays/prod` parameterize image tags, replicas, resource limits, and HPA targets.
- **CI**: GitHub Actions runs lint, type-check, unit tests, integration tests against compose, and builds multi-arch images per service.

## 10. What we deliberately did not build

- A vector DB. pgvector is sufficient at the scale this platform targets. Swap-in for Pinecone/Weaviate is a 100-line adapter when needed.
- A workflow DSL. Workflows are declared in Python; we may add YAML later but the type system is more valuable than declarative config until the platform stabilizes.
- A model gateway with caching of full prompts. Cache invalidation in the presence of retrieved memory is hard enough that a separate caching layer would lie more than it helps. We cache embeddings and critique scores instead.

## 11. Roadmap

- [ ] Multi-region active-active deployment with NATS leaf nodes.
- [ ] Constraint-based agent planner (LMQL-style).
- [ ] Per-tenant fine-tuned reliability calibration.
- [ ] Cost-aware fallback routing (factor $/token into the decision).
- [ ] WASM sandbox for tool-calling executors.
