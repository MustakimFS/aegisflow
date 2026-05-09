"""Validator agent - second-pass critique. Cheap model, fixed rubric."""

from __future__ import annotations

from aegis_core.schemas import AgentKind, AgentOutput

from orchestrator.agents.base import Agent, AgentContext
from orchestrator.llm_client import LLMClient


class ValidatorAgent(Agent):
    kind = AgentKind.VALIDATOR
    name = "validator"

    def __init__(self, llm: LLMClient, provider: str = "mock") -> None:
        self._llm = llm
        self.provider = provider
        self.model = "validator-1"

    async def run(self, ctx: AgentContext) -> AgentOutput:
        upstream = ctx.inputs.get("upstream_output", "")
        prompt = (
            "You are a strict validator. Score the upstream output 0..1 on three axes:\n"
            "  - groundedness (claims supported by retrieved context)\n"
            "  - structural validity\n"
            "  - relevance to the question\n"
            f"Upstream output: {upstream}\n"
            'Return JSON: {"groundedness": 0..1, "structural": 0..1, "relevance": 0..1, '
            '"notes": "..."}'
        )
        invocation = self.envelope(ctx, prompt)
        return await self._llm.invoke(
            self.provider, invocation, timeout_seconds=ctx.deadline_seconds
        )
