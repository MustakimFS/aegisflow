"""Planner agent - decomposes a task into a structured plan."""

from __future__ import annotations

from aegis_core.schemas import AgentKind, AgentOutput

from orchestrator.agents.base import Agent, AgentContext
from orchestrator.llm_client import LLMClient


class PlannerAgent(Agent):
    kind = AgentKind.PLANNER
    name = "planner"

    def __init__(self, llm: LLMClient, provider: str = "mock") -> None:
        self._llm = llm
        self.provider = provider
        self.model = "planner-1"

    async def run(self, ctx: AgentContext) -> AgentOutput:
        prompt = (
            "You are a planner. Decompose the user's task into 2-5 ordered steps.\n"
            f"Task: {ctx.inputs.get('task') or ctx.inputs.get('topic')}\n"
            'Return JSON: {"steps": ["...", "..."]}'
        )
        invocation = self.envelope(ctx, prompt)
        return await self._llm.invoke(self.provider, invocation, timeout_seconds=ctx.deadline_seconds)
