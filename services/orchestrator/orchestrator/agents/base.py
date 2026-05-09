"""Agent abstraction. Every agent is a stateless callable that maps context → output."""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any

from aegis_core.schemas import AgentInvocation, AgentKind, AgentOutput


@dataclass
class AgentContext:
    """Inputs to an agent invocation.

    The orchestrator hydrates this from the workflow run + memory retrieval +
    upstream node outputs before delegating to the agent.
    """

    run_id: str
    trace_id: str
    workflow: str
    node_id: str
    inputs: dict[str, Any]
    retrieved: list[dict[str, Any]] = field(default_factory=list)
    deadline_seconds: float = 30.0
    attempt: int = 1


class Agent(abc.ABC):
    """Contract for every agent implementation."""

    kind: AgentKind
    name: str
    provider: str = "internal"
    model: str = "n/a"

    @abc.abstractmethod
    async def run(self, ctx: AgentContext) -> AgentOutput: ...

    def envelope(self, ctx: AgentContext, prompt: str) -> AgentInvocation:
        return AgentInvocation(
            agent_id=self.name,
            kind=self.kind,
            provider=self.provider,
            model=self.model,
            prompt=prompt,
            retrieved_context=ctx.retrieved,
            attempt=ctx.attempt,
        )
