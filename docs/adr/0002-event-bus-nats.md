# ADR-0002: NATS JetStream over Kafka for the event bus

**Status**: accepted
**Date**: 2026-02-22

## Context

The platform needs an async event bus for: replay log fan-out, chaos triggers,
workflow state transitions, and cross-service audit. Two obvious options:
Apache Kafka and NATS JetStream.

## Decision

Use NATS JetStream.

## Rationale

1. **Operational footprint.** NATS runs as a single binary with no ZooKeeper
   / KRaft to manage. For a platform that targets self-hosting in customer
   k8s clusters, the lower op cost wins.
2. **Latency.** NATS pub-sub round-trip is sub-millisecond at the scales we
   care about. Kafka's batching adds 5-50ms even at low throughput.
3. **Subjects vs. topics.** NATS subjects support hierarchical wildcards
   (`workflow.*.completed`), which maps cleanly onto our trace-driven fan-out.
4. **JetStream gives us at-least-once + replay.** That's all we need -
   we're not doing log compaction or stream processing.

## Costs we accept

- Smaller ecosystem than Kafka. Connectors to S3, BigQuery, Snowflake exist
  but aren't as mature.
- Less institutional familiarity. Most engineers know Kafka; few know NATS.
  Mitigation: thin internal wrapper exposes a Kafka-shaped API.

## Alternatives considered

- **Apache Kafka**: heavyweight, well-known, overkill for our event volumes.
  We'd be using 5% of its capability.
- **AWS SQS + SNS**: vendor lock-in. We need to run on customer-owned k8s
  clusters that may not be on AWS.
- **Postgres LISTEN/NOTIFY**: insufficient for fan-out; doesn't survive
  consumer disconnects.

## Revisit when

If a customer requires Kafka-shaped infrastructure for compliance reasons
(streaming audit feeds into SIEM), revisit. The bus is well-encapsulated
in `aegis_core.bus` (TODO) so the swap is a one-week project.
