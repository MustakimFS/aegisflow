# AegisFlow

**Deterministic Reliability Layer for Non-Deterministic AI Systems**

AegisFlow is an orchestration, reliability, and observability platform for production AI agents. It sits between your application and your model providers, turning unreliable LLM calls into deterministic, recoverable, auditable workflows.

> _"AI Kubernetes meets SRE Reliability Engineering."_

---

## Why this exists

Modern AI agents are non-deterministic. They:

- hallucinate facts that look correct,
- return malformed JSON,
- timeout unpredictably under load,
- silently degrade when upstream providers throttle,
- produce different outputs for the same input.

Traditional backend infrastructure is deterministic. Service meshes, retries, circuit breakers, and schema validators all assume failures are *categorical* - a request either succeeded or it didn't. LLM systems break that assumption: a "successful" response can still be wrong, malformed, or unsafe.

AegisFlow bridges that gap. It treats every agent invocation as a probabilistic operation that must be **scored**, **validated**, **recovered**, and **traced** before its output is allowed to leave the platform.

## What it does

| Capability | What it means in practice |
| --- | --- |
| **Agent Orchestration** | Coordinate planner / executor / validator / fallback agents across distributed workflows |
| **Reliability Engine** | Confidence scoring, hallucination heuristics, adaptive retries, circuit breakers per provider |
| **Guardrail Layer** | JSON schema validation, structural repair, output sanitization, AI-critique pass |
| **Semantic Memory** | pgvector-backed RAG with rerank, contextual replay, conversation memory |
| **Replay & Debug** | Deterministic replay of historical executions, diffing across model versions |
| **Chaos Engineering** | Inject latency, malformed outputs, provider outages, hallucinations on demand |
| **Observability** | OpenTelemetry traces, Prometheus metrics, Grafana dashboards for every signal that matters |

## High-level architecture

```
                           ┌──────────────────────────┐
   client ──── HTTPS ────► │      API Gateway         │  auth · rate limit · trace ID
                           └────────────┬─────────────┘
                                        │
                           ┌────────────▼─────────────┐
                           │   Agent Orchestrator     │  workflow engine · state machine
                           └────────────┬─────────────┘
                                        │
       ┌────────────┬─────────┬─────────┼─────────┬──────────┬──────────────┐
       ▼            ▼         ▼         ▼         ▼          ▼              ▼
 ┌──────────┐ ┌──────────┐ ┌──────┐ ┌─────────┐ ┌──────┐ ┌─────────┐ ┌──────────────┐
 │Reliability│ │Guardrails│ │Memory│ │  Replay │ │Chaos │ │ LLM     │ │ Observability│
 │  Engine  │ │   Layer  │ │ (RAG)│ │  Engine │ │Engine│ │Providers│ │ (OTEL+Prom)  │
 └──────────┘ └──────────┘ └──────┘ └─────────┘ └──────┘ └─────────┘ └──────────────┘
       └──────────── shared event bus (NATS JetStream) ────────────────┘
                          │
              Postgres + pgvector · Redis · S3
```

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the deep dive, and [`docs/`](docs/) for ADRs and per-component design notes.

## Repository layout

```
aegisflow/
├── libs/
│   └── aegis_core/          shared primitives - circuit breaker, retry, tracing, schemas
├── services/
│   ├── gateway/             FastAPI edge - auth, rate-limit, trace ingress
│   ├── orchestrator/        workflow engine + agent abstractions
│   ├── reliability/         confidence scoring · hallucination heuristics · fallback routing
│   ├── guardrails/          JSON schema validation · structural repair · sanitization
│   ├── memory/              pgvector RAG · rerank · contextual replay
│   ├── replay/              event-sourced execution log · deterministic replay
│   └── chaos/               failure injection · scenario engine
├── infra/
│   ├── docker/              OTEL collector, prometheus, grafana configs
│   └── k8s/                 base manifests + dev/prod overlays
├── docs/                    architecture deep-dives + ADRs
├── tests/                   unit + integration suites
└── docker-compose.yml       full local stack
```

## Quickstart (local dev)

Requirements: Docker 24+, Python 3.12+, `uv` (or `pip`), `make`.

```bash
make bootstrap          # install deps for all services into a single workspace
make up                 # docker-compose up - full stack with otel + grafana + nats + postgres
make seed               # populate sample agents, memory, and chaos scenarios
make demo               # run an end-to-end workflow against the gateway
```

The Grafana dashboard at `http://localhost:3000` will show every trace and reliability metric in real time.

## Running a workflow

```bash
curl -X POST http://localhost:8080/v1/workflows \
  -H "Authorization: Bearer dev-token" \
  -H "Content-Type: application/json" \
  -d '{
    "workflow": "research_summarize",
    "input": {"topic": "post-quantum cryptography migration"},
    "policies": {
      "max_retries": 3,
      "min_confidence": 0.75,
      "fallback_chain": ["primary", "secondary", "rule-based"]
    }
  }'
```

The response includes a `trace_id` you can drop into Grafana or `GET /v1/replay/{trace_id}` to walk every prompt, retrieval, score, retry, and fallback decision the system made.

## Engineering principles

1. **Failure is the default.** Every cross-service call goes through a circuit breaker; every agent output is treated as untrusted until validated.
2. **Determinism through replay.** Every execution is event-sourced. Given the same trace ID and a frozen model snapshot, the system reproduces the run bit-for-bit.
3. **Observability is not optional.** A code path without a trace span, a metric, and a structured log doesn't get merged.
4. **Backpressure beats buffering.** Queues have bounded capacity; overload sheds load explicitly rather than silently degrading latency.
5. **Stateless compute, stateful storage.** Services scale horizontally; all durable state lives in Postgres, Redis, or NATS JetStream.

## License

MIT - see [`LICENSE`](LICENSE).
