# ADR-0001: Microservices over modular monolith

**Status**: accepted
**Date**: 2026-02-18

## Context

We need to decide whether AegisFlow ships as a modular monolith with internal
boundaries, or as separate services from day one.

## Decision

Ship as separate services from day one, communicating over HTTP+gRPC and
NATS JetStream.

## Rationale

1. **Independent failure domains.** The reliability engine is CPU-bound during
   scoring; the memory service is I/O-bound during retrieval. Co-locating
   them means a CPU spike on one path tail-latency-impacts the other.
2. **Independent scaling.** Token-heavy customers scale orchestrator pods;
   rerank-heavy customers scale memory pods. With a monolith, a single hot
   path forces the whole binary to scale.
3. **Provable isolation for chaos testing.** A core selling point is "you
   can take down the reliability service and the orchestrator gracefully
   degrades". This is much easier to demonstrate when the boundary is a
   process boundary, not a function call.
4. **Polyglot future-proofing.** The reliability engine is a candidate for a
   Rust rewrite if scoring throughput becomes the bottleneck. Service
   boundaries make that swap mechanical.

## Costs we accept

- 7 services �- Dockerfile �- Helm value �- CI matrix entry. Real overhead.
- Cross-service tracing must work *perfectly*, or debugging becomes worse
  than a monolith. We invested heavily in OpenTelemetry from day one.
- Local dev requires `docker compose`. We refuse to ship a "local mode"
  that runs everything in-process - it would diverge from production and
  hide bugs.

## Alternatives considered

- **Modular monolith** (FastAPI app with internal `aegisflow.{gateway,
  orchestrator,...}` modules): cheaper to operate, harder to scale
  individual hot paths, harder to demonstrate fault isolation.
- **Serverless functions**: cold-start latency unacceptable for the synchronous
  request path. Could fit chaos / replay async paths but the operational
  model split would be confusing.

## Revisit when

If we hit < 100 RPS sustained on the platform after a year, the operational
overhead of microservices isn't paying for itself; revisit.
