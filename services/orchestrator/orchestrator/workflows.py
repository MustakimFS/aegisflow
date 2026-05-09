"""Built-in workflow definitions. Real deployments load these from a registry."""

from __future__ import annotations

from aegis_core.schemas import Policies, WorkflowDefinition, WorkflowNode

RESEARCH_SUMMARIZE = WorkflowDefinition(
    name="research_summarize",
    version="1",
    nodes=[
        WorkflowNode(id="plan", agent="planner", description="decompose the task"),
        WorkflowNode(
            id="execute",
            agent="executor",
            inputs_from=["plan"],
            description="produce an answer using retrieved memory",
        ),
        WorkflowNode(
            id="validate",
            agent="validator",
            inputs_from=["execute"],
            description="critique the executor output",
        ),
    ],
    default_policies=Policies(
        max_retries=2,
        min_confidence=0.70,
        deadline_seconds=20.0,
        fallback_chain=["mock", "openai", "rule_based_fallback"],
    ),
)

CLASSIFY = WorkflowDefinition(
    name="classify",
    version="1",
    nodes=[
        WorkflowNode(id="execute", agent="executor", description="single-shot classification"),
    ],
    default_policies=Policies(
        max_retries=3,
        min_confidence=0.80,
        deadline_seconds=8.0,
        fallback_chain=["mock", "rule_based_fallback"],
    ),
)


REGISTRY: dict[str, WorkflowDefinition] = {
    RESEARCH_SUMMARIZE.name: RESEARCH_SUMMARIZE,
    CLASSIFY.name: CLASSIFY,
}
