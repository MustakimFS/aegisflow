# 03 - Reliability Engine

The reliability engine is the differentiator. Most of this codebase is plumbing;
this document is the substance.

## Problem statement

A model returns a 200. The JSON parses. The structure looks plausible. But:

- Half the citations are fabricated.
- The numbers contradict the retrieved context.
- The model "helpfully" answered a different question.

Traditional reliability tooling cannot catch any of this. The transport layer
sees success, the schema validator sees success, the alerting pipeline sees
green dashboards. The only signal something is wrong is *downstream* - when
a user complains, a customer churns, or an automated decision causes harm.

The reliability engine catches these failures at the layer where they happen:
between the model output and the orchestrator's accept/fallback decision.

## Composite confidence

```
confidence = w_struct  · structural_score
           + w_ground  · grounding_score
           + w_critic  · critique_score
           + w_history · historical_provider_score
           − w_anom    · anomaly_penalty
```

Each component is bounded `[0, 1]`. The composite is clamped to `[0, 1]`.

### Default weights

| Component | Weight | Rationale |
| --- | --- | --- |
| Structural | 0.30 | A malformed response can never be correct; weight it heavily but allow some recovery via guardrails |
| Grounding | 0.30 | The most reliable signal we have when retrieved context is good |
| Critique | 0.20 | Useful but expensive - token cost rises linearly with outputs |
| History | 0.10 | Provider stability over the last 5 minutes; smooths transient variance |
| Anomaly penalty | 0.30 | Subtracted; capped at 1.0 |

Workflow-specific weights override these. A `code_review` workflow weights
critique at 0.35 because language-server signals aren't available. A
`classify` workflow weights structural at 0.50 because the output is
single-token.

## Structural score

```python
def structural_score(raw: str) -> float:
    try:
        json.loads(raw); return 1.0
    except JSONDecodeError:
        if abs(raw.count("{") - raw.count("}")) <= 1: return 0.5
        return 0.0
```

Rationale: a *recoverable* JSON error (unbalanced brace, trailing comma) is
fundamentally different from a *categorical* parse failure (response was prose).
The guardrails service can repair the former; the latter requires a retry.

## Grounding score

For each declarative sentence in the output, compute token Jaccard overlap
with the retrieved context. A sentence is "grounded" if overlap ≥ 0.25.

```
grounding = #grounded_sentences / #total_sentences
```

This is a *fast proxy* for embedding-based grounding. The memory service
exposes a `/v1/ground` endpoint that does the more expensive cosine-similarity
check, used when the proxy returns borderline values.

### Why not embeddings everywhere?

Cost. Computing per-sentence embeddings on every output adds 30–80ms and
0.0001¢/token. The token-overlap proxy is good enough at 95% and costs ~1ms.
We escalate only on ambiguous cases.

## Critique score

A second LLM call rates the output on a fixed rubric:

```
groundedness ∈ [0,1]    "Are the claims supported by the retrieved context?"
structural   ∈ [0,1]    "Is the output the requested structure?"
relevance    ∈ [0,1]    "Does the output answer the asked question?"
```

We use a smaller, cheaper model for critique than for execution. Two-tier
"executor + critic" patterns generally beat single-tier high-temperature
sampling on the SuperGLUE / TriviaQA reliability benchmarks.

Critique outputs are cached aggressively, keyed on `hash(prompt + raw_output)`.
A workflow that retries the same input only pays for critique once.

## Historical provider score

Bayesian shrinkage:

```
weight = n / (n + 50)
score  = weight * recent_success_rate + (1 - weight) * 0.8
```

When `n` is small, we trust the prior (0.8). When `n` ≥ 200 we trust the rate
fully. The 50-sample crossover point is tuned on synthetic outage data - it
makes the engine react within 30 seconds at typical traffic without
overreacting to a single bad request.

## Anomaly penalty

Diminishing returns: 5 anomalies aren't 5�- as bad as 1.

```
penalty = 1 - exp(-0.5 * num_anomalies)
```

Anomalies with weight:

| Tag | Weight | What we look for |
| --- | --- | --- |
| `injection_marker` | hard reject | "ignore previous instructions", `<\|im_start\|>` |
| `refusal` | force fallback | "I cannot", "As an AI" |
| `hallucination_pattern` | 1.0 | "according to recent studies", "experts agree" |
| `repetition` | 1.0 | n-gram repeats above 40% threshold |
| `length_outlier` | 0.7 | tokens_out outside `[8, 4096]` |
| `low_grounding` | 1.0 | grounding_score < 0.5 |
| `schema_failure` | 0.5 | structural_score < 1.0 |

## Recommended action

```python
if INJECTION_MARKER:    return REJECT
if refusal:             return FALLBACK
if confidence ≥ τ:      return ACCEPT
if confidence ≥ τ - 0.1 and SCHEMA_FAILURE: return RETRY  # repair on retry
if confidence ≥ τ - 0.2: return RETRY
return FALLBACK
```

The engine *recommends*; the orchestrator *decides*. This separation matters:
the same recommendation translates differently in a financial workflow
(reject) vs. a research workflow (try harder).

## Calibration

The reliability engine ships with weights tuned on a held-out benchmark:

- **Source**: 500 hand-labeled outputs across 5 workflows (research, classify,
  extract, summarize, code_review).
- **Labels**: human review on a 4-point rubric - accept / minor / major / reject.
- **Optimization**: grid search over weights minimizing `MSE(confidence, label_score)`
  on a 80/20 split.

Per-tenant calibration is on the roadmap. The current weights are a robust
starting point; production deployments collect real outcomes via the replay
log and fit tenant-specific weights every 24h.

## What this does *not* do

- **Catch correct-but-irrelevant outputs**: if the model answered a different
  question correctly, grounding may be high. Mitigation: critique catches it.
- **Catch novel hallucination patterns**: heuristics are reactive. New
  hallucination phrasings sneak through until added to the pattern list.
  Mitigation: critique acts as a backstop; replay log surfaces drift.
- **Replace human review**: this layer turns "every output is suspect" into
  "5% of outputs are flagged for review". The human still matters.
