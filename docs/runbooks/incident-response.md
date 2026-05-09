# Runbook - Incident Response

This is the on-call playbook. Keep it short; longer than 5 minutes of reading
during an incident means it failed.

## Symptom: client-facing 5xx spike

1. Open the **AegisFlow Reliability Overview** Grafana dashboard.
2. Check `aegisflow_workflow_duration_seconds_count{status="failed"}` rate
   vs. `status="succeeded"`. Is the failure rate > 5%?
3. Check `aegisflow_circuit_state` - any provider showing 2 (OPEN)?
   - If yes: provider outage. Verify on the provider's status page. The
     fallback chain should already be carrying traffic; if not, see
     "fallback chain not engaging".
4. Check gateway → orchestrator span errors in Tempo.
5. Check `kubectl get pods -n aegisflow` for pod restarts.

**Mitigation**: if a provider is hard-down, manually open its breaker via
the orchestrator admin endpoint (`POST /admin/circuit/{provider}/open`)
to short-circuit the cooldown wait.

## Symptom: confidence histogram shifting left

The avg confidence panel drops from ~0.85 to ~0.65 over an hour.

1. Check `aegisflow_hallucination_flags_total` by heuristic. Which
   heuristic is firing most?
2. Check `aegisflow_memory_recall_at_k` - has retrieval quality degraded?
   - If yes: memory index may be stale or pgvector planner regressed.
     `EXPLAIN ANALYZE` on a sample retrieval query.
3. Check provider model version - did a vendor silently switch a model?
   - Mitigation: pin model version in `services/orchestrator/orchestrator/llm_client.py`.

## Symptom: latency cliff at p99

1. Check `kubectl top pods -n aegisflow`. Which service is throttled?
2. Check `aegisflow_retries_total` - are retries inflating?
   - If yes: confidence threshold may be too aggressive. Consider relaxing
     `RELIABILITY_MIN_CONFIDENCE` for the affected workflow.
3. Check pgvector index health: `SELECT pg_size_pretty(pg_total_relation_size('memory_chunks_embedding_hnsw_idx'));`

## Symptom: replay events accumulating

`aegisflow_replay_events_pending` (TODO add this metric) is climbing.

1. Replay store may be back-pressured. Check disk on Postgres.
2. NATS JetStream consumer may be stalled: `nats stream report -a` in
   the NATS pod.
3. Worst case: temporarily disable replay append by setting
   `REPLAY_DISABLED=true` on orchestrator. The system runs without replay,
   we just lose audit data for the duration.

## Fallback chain not engaging

When a primary provider is down but the fallback isn't being used:

1. Verify the fallback chain in the workflow definition includes a healthy
   provider.
2. Verify the secondary provider's circuit breaker is CLOSED.
3. Check `aegisflow_fallback_total` - is the counter incrementing at all?

If circuits are stuck OPEN even after cooldown, the breaker may have
extended cooldown after consecutive HALF_OPEN failures. Restart the
orchestrator pod to reset breaker state (in-memory, no Redis sync today).

## Postgres pressure

Symptoms: orchestrator readyz failing, write latency climbing.

1. `SELECT pid, query, state, wait_event_type FROM pg_stat_activity WHERE state != 'idle';`
2. Common culprit: long-running replay queries against `replay_events`
   without `LIMIT`. Add the limit, kill the query.
3. Vacuum analyze if it's been a while.

## Escalation

- L1: on-call engineer.
- L2: platform team lead.
- L3: paging engineer at the affected provider (have account contacts in
  the ops doc).

If a customer's tenant ID is in the trace ID context, notify their primary
contact via the standard customer-facing comms channel - *don't* email from
the on-call engineer's address.
