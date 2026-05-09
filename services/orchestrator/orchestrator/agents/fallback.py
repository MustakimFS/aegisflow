"""Deterministic rule-based fallback. Triggered as the last step in a fallback chain."""

from __future__ import annotations

import json

from aegis_core.schemas import AgentKind, AgentOutput

from orchestrator.agents.base import Agent, AgentContext


class RuleBasedFallbackAgent(Agent):
    """Static, deterministic answer. Lets us return a structured 'graceful failure' instead of 5xx.

    This is what makes the system *self-healing* in the worst case: when every
    upstream model is down, the orchestrator still returns a coherent envelope
    that downstream apps can branch on.
    """

    kind = AgentKind.FALLBACK
    name = "rule_based_fallback"
    provider = "internal"
    model = "rule-based"

    async def run(self, ctx: AgentContext) -> AgentOutput:
        body = {
            "answer": None,
            "fallback": True,
            "reason": "All primary providers exhausted; returning deterministic fallback.",
            "trace_id": ctx.trace_id,
            "run_id": ctx.run_id,
        }
        raw = json.dumps(body)
        return AgentOutput(
            agent_id=self.name,
            raw_text=raw,
            parsed=body,
            tokens_in=0,
            tokens_out=0,
            latency_ms=0,
            finish_reason="fallback",
        )
