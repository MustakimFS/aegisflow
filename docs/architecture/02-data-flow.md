# 02 - Data Flow

This is the canonical end-to-end story for one request, told in detail.

## Prerequisites

- The client has a JWT issued by the tenant IDP, with claims `sub`, `tenant_id`, `aud=aegisflow.api`.
- The workflow `research_summarize` is registered (see `services/orchestrator/orchestrator/workflows.py`).
- The memory service has been seeded with relevant docs.

## Step-by-step

### 1. Gateway ingress

```http
POST /v1/workflows
Authorization: Bearer <jwt>
Content-Type: application/json

{
  "workflow": "research_summarize",
  "input": {"topic": "post-quantum cryptography"},
  "policies": {"min_confidence": 0.75, "max_retries": 2}
}
```

The gateway:

1. Validates the JWT (`gateway.auth.authenticate`). On failure → 401.
2. Resolves `principal.tenant_id`.
3. Charges the tenant token bucket (`gateway.rate_limit.RateLimiter.allow`).
   On overflow → 429 with `Retry-After`.
4. Mints a 16-byte hex trace ID, opens a root span, binds `trace_id` into
   structlog contextvars.
5. Forwards to `http://orchestrator:8081/v1/workflows` with headers:
   `x-trace-id`, `x-tenant-id`, `x-subject`.

### 2. Orchestrator: persist & enter the engine

```python
run = WorkflowRun.new(request, run_id=ulid(), trace_id=trace_id)
await run_store.insert(tenant_id, run)
response = await engine.execute(run, tenant_id, policies)
```

The run is persisted *before* execution begins. If the orchestrator pod
crashes mid-flight, the run is still recoverable (status=`running` in
Postgres; reaper job marks it `deadline_exceeded` after timeout).

### 3. Engine: walk the DAG

The workflow `research_summarize` is `plan → execute → validate`. The engine
computes in-degrees, finds ready nodes (initially `plan`), and runs them
inside a `deadline_budget(policies.deadline_seconds)`.

For each node:

```python
retrieved = await memory.retrieve(tenant_id, query)
output = await agent.run(ctx)
report = await reliability.score(invocation, output, policies)
decision = decide_route(report, current_provider, fallback_chain, attempts, max_retries)
```

### 4. Reliability scoring (per node)

The reliability service computes:

```
structural_score   ← parse JSON
grounding_score    ← token overlap with retrieved context
critique_score     ← validator-agent rubric (cached)
historical_score   ← rolling provider success rate (Bayesian-shrunk)
anomaly_penalty    ← refusal/repetition/length/injection markers

confidence = w·components - penalty
```

Returns a `ReliabilityReport` with a `recommended_action`:
- `ACCEPT`  - confidence ≥ threshold, no anomalies that block
- `RETRY`   - confidence is borderline; one more attempt may succeed
- `FALLBACK`- advance to the next provider in the chain
- `REJECT`  - fundamental failure (injection marker, etc.)

### 5. Routing decision

`orchestrator.routing.decide` translates the recommendation into a concrete
next step. This separation matters: the same low-confidence output retries
on a research workflow but rejects on a financial one - the *policy* lives
with the orchestrator, the *signal* lives with the reliability engine.

### 6. Guardrails (terminal node only)

Once the engine accepts an output, it asks the guardrails service to:

1. Repair JSON if structurally damaged.
2. Validate against `policies.output_schema`.
3. Sanitize PII / strip prompt-injection markers.

Guardrails *can* fail the workflow even after reliability accepts, because
schema enforcement is downstream of confidence scoring.

### 7. Replay append

After every node completes, the engine fires a `node_completed` event to
the replay service. The event includes prompt, retrieved context, raw
output, parsed output, reliability components, and decision metadata.

This is what makes replay deterministic: given the trace ID and a frozen
provider snapshot, the system can reconstruct the run bit-for-bit.

### 8. Final response

The orchestrator returns:

```json
{
  "run_id": "01HZ...",
  "trace_id": "fa3b...",
  "status": "succeeded",
  "output": {"summary": "...", "citations": [...]},
  "confidence": 0.86,
  "fallback_depth": 0,
  "retries": 1,
  "duration_ms": 2417
}
```

The gateway adds `x-trace-id` to the response headers and returns it.

## Failure paths worth knowing

| Failure | What happens |
| --- | --- |
| JWT expired | Gateway → 401 immediately |
| Rate limit hit | Gateway → 429, Retry-After |
| Orchestrator unreachable | Gateway → 503 |
| Postgres down | Orchestrator readiness probe fails → k8s pulls pod from rotation |
| Provider 5xx | Circuit breaker increments failure; retry with jitter; then fallback |
| Confidence below threshold | Retry → fallback → rule-based fallback (always returns structured envelope) |
| Schema violation | Guardrails repairs if possible; else 422 with details |
| Workflow deadline exceeded | Engine returns `status=deadline_exceeded` with partial replay log |
| Reliability service down | Orchestrator fails closed (rejects); replay still records the failure |

## Sequence diagram

```
client ─────► gateway ─────► orchestrator ─────► memory     (retrieve)
                                  ├─────────► provider     (agent.run)
                                  ├─────────► reliability  (score)
                                  ├─────────► guardrails   (validate)
                                  └─────────► replay       (append)
client �-�──── gateway �-�──── orchestrator
```

Trace ID propagates through every hop; `x-trace-id` is the join key.
