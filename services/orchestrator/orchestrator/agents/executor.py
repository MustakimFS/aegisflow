"""Executor agent - performs a step using retrieved context."""

from __future__ import annotations

from aegis_core.schemas import AgentKind, AgentOutput

from orchestrator.agents.base import Agent, AgentContext
from orchestrator.llm_client import LLMClient


class ExecutorAgent(Agent):
    kind = AgentKind.EXECUTOR
    name = "executor"

    def __init__(self, llm: LLMClient, provider: str = "mock") -> None:
        self._llm = llm
        self.provider = provider
        self.model = "executor-1"

    async def run(self, ctx: AgentContext) -> AgentOutput:
        context_block = "\n".join(
            f"- ({i+1}) {item.get('text', '')}" for i, item in enumerate(ctx.retrieved[:5])
        )
        prompt = (
            "You are an executor. Use the retrieved context to answer.\n"
            f"Question: {ctx.inputs.get('question') or ctx.inputs.get('topic')}\n"
            f"Context:\n{context_block}\n"
            'Return JSON: {"answer": "...", "citations": ["..."]}'
        )
        invocation = self.envelope(ctx, prompt)
        return await self._llm.invoke(
            self.provider, invocation, timeout_seconds=ctx.deadline_seconds
        )
