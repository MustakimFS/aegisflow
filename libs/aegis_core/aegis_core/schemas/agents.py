"""Agent invocation envelopes. Used by orchestrator → reliability/guardrails handoff."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class AgentKind(StrEnum):
    PLANNER = "planner"
    EXECUTOR = "executor"
    VALIDATOR = "validator"
    FALLBACK = "fallback"
    CRITIQUE = "critique"


class AgentInvocation(BaseModel):
    """A single agent call. Persisted as part of the replay log."""

    agent_id: str
    kind: AgentKind
    provider: str
    model: str
    prompt: str
    retrieved_context: list[dict[str, Any]] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    attempt: int = 1


class AgentOutput(BaseModel):
    """The raw output of an agent, pre-validation. Reliability scores attach later."""

    agent_id: str
    raw_text: str
    parsed: dict[str, Any] | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    finish_reason: str | None = None
