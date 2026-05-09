"""Workflow / run domain models. These cross service boundaries - keep them stable."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class WorkflowStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"  # passed reliability rejection
    DEADLINE_EXCEEDED = "deadline_exceeded"


class NodeStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    RETRYING = "retrying"
    FALLBACK = "fallback"
    FAILED = "failed"
    SKIPPED = "skipped"


class Policies(BaseModel):
    """Per-workflow runtime policies. Can be overridden by request."""

    max_retries: int = Field(default=3, ge=0, le=10)
    min_confidence: float = Field(default=0.70, ge=0.0, le=1.0)
    deadline_seconds: float = Field(default=30.0, gt=0)
    fallback_chain: list[str] = Field(default_factory=lambda: ["primary", "secondary"])
    grounding_required: bool = False
    output_schema: dict[str, Any] | None = None


class WorkflowNode(BaseModel):
    id: str
    agent: str
    inputs_from: list[str] = Field(default_factory=list)
    timeout_seconds: float | None = None
    description: str | None = None


class WorkflowDefinition(BaseModel):
    name: str
    version: str = "1"
    nodes: list[WorkflowNode]
    default_policies: Policies = Field(default_factory=Policies)

    @field_validator("nodes")
    @classmethod
    def _nonempty(cls, v: list[WorkflowNode]) -> list[WorkflowNode]:
        if not v:
            raise ValueError("workflow must have at least one node")
        return v


class WorkflowRequest(BaseModel):
    workflow: str
    input: dict[str, Any]
    policies: Policies | None = None
    idempotency_key: str | None = None


class WorkflowResponse(BaseModel):
    run_id: str
    trace_id: str
    status: WorkflowStatus
    output: dict[str, Any] | None = None
    confidence: float | None = None
    fallback_depth: int = 0
    retries: int = 0
    duration_ms: int
    error: dict[str, Any] | None = None


class WorkflowRun(BaseModel):
    run_id: str
    trace_id: str
    workflow: str
    status: WorkflowStatus
    started_at: datetime
    finished_at: datetime | None = None
    request: WorkflowRequest
    response: WorkflowResponse | None = None
    node_states: dict[str, NodeStatus] = Field(default_factory=dict)

    @classmethod
    def new(cls, request: WorkflowRequest, run_id: str, trace_id: str) -> WorkflowRun:
        return cls(
            run_id=run_id,
            trace_id=trace_id,
            workflow=request.workflow,
            status=WorkflowStatus.PENDING,
            started_at=datetime.now(UTC),
            request=request,
        )
