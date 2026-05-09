# 04 - Orchestration

This document describes how the orchestrator turns a workflow definition into a
sequence of agent calls.

## Workflow definition

```python
WorkflowDefinition(
    name="research_summarize",
    nodes=[
        WorkflowNode(id="plan",     agent="planner"),
        WorkflowNode(id="execute",  agent="executor", inputs_from=["plan"]),
        WorkflowNode(id="validate", agent="validator", inputs_from=["execute"]),
    ],
    default_policies=Policies(...),
)
```

A `WorkflowNode` declares its agent and which upstream nodes' outputs it
consumes. The engine builds a DAG, computes in-degrees, and walks ready
nodes in topological order.

## DAG walker (high level)

```
in_degree, edges = build_topology(wf.nodes)
while in_degree:
    ready = [n for n, d in in_degree.items() if d == 0]
    for node in ready:
        run_node(node)            # → output, report, attempts, fallback_depth
        record_replay(node, output, report)
    advance_topology(ready)
```

Independent nodes execute concurrently via `asyncio.gather`; dependent nodes
wait on the barrier. This isn't toy parallelism - a workflow that fans out to
10 retrievers in parallel sees real wall-clock wins.

## Per-node loop (`_run_node`)

```
chain          = workflow.fallback_chain
provider       = chain[0]
attempts       = 0
fallback_depth = 0

loop:
    attempts += 1
    output  = agent.run(ctx, provider)
    report  = reliability.score(output, policies)
    decision = routing.decide(report, ...)

    if decision.accept:        return output, report
    if decision.retry:         continue
    if decision.fallback:
        provider        = next_in(chain, provider)
        fallback_depth += 1
        if provider == "rule_based_fallback":
            return rule_fallback.run(ctx)
    if decision.reject:        raise AegisError(decision.reason)
```

The loop terminates in one of three ways:

1. **Accept** - output passes reliability scoring + (optional) guardrail validation.
2. **Reject** - fundamental failure (injection marker, exhausted chain).
3. **Rule-based fallback** - every upstream provider failed; return a
   structured deterministic envelope so callers always get a parseable response.

## Why fallback to deterministic last

Most platforms surface a 5xx when all providers are exhausted. AegisFlow
returns a structured `{"fallback": true, "reason": "..."}` envelope instead.
This matters for downstream applications:

- A 5xx requires retry logic in every caller.
- A structured fallback lets callers branch *in their normal happy-path code*.

The orchestrator clearly signals the fallback in `fallback_depth > 0` and
`status` so observability captures the degraded mode.

## Concurrency model

Each `_run_node` call runs in its own task. Within a node:

- `memory.retrieve` is a single network round trip.
- `agent.run` is wrapped by `with_timeout` against the workflow's
  `deadline_budget`.
- `reliability.score` is a single network round trip; the engine fails *closed*
  if reliability is unreachable (no scoring → no acceptance).
- `replay.append` is fire-and-forget - its failure does not block the workflow.

## Provider selection per attempt

The engine swaps `agent.provider` between attempts. Agents are stateless;
the agent abstraction never holds a provider reference long-term. This lets
us swap providers mid-workflow without re-instantiating agents.

## Memory retrieval

The engine retrieves *before* the agent runs, not after. The retrieved
context becomes part of the agent's prompt and is also passed to the
reliability engine so it can compute grounding scores against the same
context the agent saw. This is a critical detail - using *different* context
for grounding than the agent used would produce nonsensical scores.

## State persistence

`workflow_runs` is updated at:

1. Insert on submission (`status=PENDING`).
2. Update to `RUNNING` once the engine starts.
3. Final update on completion with the response payload.

If the orchestrator crashes mid-run, a reaper job in cron looks for runs in
`RUNNING` status older than 2�- the configured deadline and marks them
`DEADLINE_EXCEEDED`. The replay log retains whatever events made it through.

## Idempotency

Clients can send `idempotency_key`. The orchestrator hashes
`(tenant_id, workflow, idempotency_key)` and checks Postgres for a recent
run. If found within a 5-minute window, return the prior response.
This prevents double-execution of expensive workflows when a client
retries on transient gateway errors.
