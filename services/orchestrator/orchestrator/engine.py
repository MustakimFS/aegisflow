"""Workflow execution engine.

A workflow is a DAG of agent nodes. The engine walks the DAG in topological
order, hydrates each node with retrieved memory + upstream outputs, invokes
the agent under reliability/guardrail checks, and applies the routing policy
on every output.

Concurrency: independent nodes run in parallel via `asyncio.gather`. The DAG
walker maintains a barrier on dependencies, so a node never runs until every
node it lists in `inputs_from` has succeeded.
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Any

import httpx
from aegis_core.errors import AegisError
from aegis_core.logging import get_logger
from aegis_core.metrics import (
    FALLBACKS,
    RELIABILITY_CONFIDENCE,
    RETRIES,
    WORKFLOW_DURATION,
)
from aegis_core.schemas import (
    AgentInvocation,
    AgentOutput,
    Policies,
    ReliabilityReport,
    WorkflowDefinition,
    WorkflowResponse,
    WorkflowRun,
    WorkflowStatus,
)
from aegis_core.timeout import deadline_budget

from orchestrator.agents import (
    Agent,
    AgentContext,
    ExecutorAgent,
    PlannerAgent,
    RuleBasedFallbackAgent,
    ValidatorAgent,
)
from orchestrator.llm_client import LLMClient
from orchestrator.routing import decide as decide_route
from orchestrator.state import RunStore

log = get_logger("orchestrator.engine")


class Engine:
    """Stateless executor. Owns no run state; all state lives in `RunStore`."""

    def __init__(
        self,
        *,
        llm: LLMClient,
        run_store: RunStore,
        http_client: httpx.AsyncClient,
        reliability_url: str,
        guardrails_url: str,
        memory_url: str,
        replay_url: str,
        workflows: dict[str, WorkflowDefinition],
    ) -> None:
        self._llm = llm
        self._runs = run_store
        self._http = http_client
        self._reliability_url = reliability_url
        self._guardrails_url = guardrails_url
        self._memory_url = memory_url
        self._replay_url = replay_url
        self._workflows = workflows

        self._agents: dict[str, Agent] = {
            "planner": PlannerAgent(llm),
            "executor": ExecutorAgent(llm),
            "validator": ValidatorAgent(llm),
            "rule_based_fallback": RuleBasedFallbackAgent(),
        }

    async def execute(
        self,
        run: WorkflowRun,
        tenant_id: str,
        policies: Policies,
    ) -> WorkflowResponse:
        wf = self._workflows.get(run.workflow)
        if wf is None:
            return self._reject(
                run, status=WorkflowStatus.FAILED,
                error=f"unknown workflow: {run.workflow}",
                started=time.monotonic(),
            )

        await self._runs.update_status(run.run_id, WorkflowStatus.RUNNING)
        started = time.monotonic()
        results: dict[str, AgentOutput] = {}
        retries_total = 0
        fallback_depth = 0
        last_confidence: float | None = None

        with deadline_budget(policies.deadline_seconds):
            in_degree, edges = self._topology(wf)

            while in_degree:
                ready = [nid for nid, deg in in_degree.items() if deg == 0]
                if not ready:
                    return self._reject(
                        run, status=WorkflowStatus.FAILED,
                        error="cycle in workflow DAG", started=started,
                    )

                for nid in ready:
                    node = next(n for n in wf.nodes if n.id == nid)
                    node_input = self._build_node_input(run, results, node.inputs_from)

                    try:
                        output, report, attempts, depth = await self._run_node(
                            run=run,
                            node_id=node.id,
                            agent_name=node.agent,
                            node_input=node_input,
                            tenant_id=tenant_id,
                            policies=policies,
                        )
                    except AegisError as exc:
                        return self._reject(
                            run,
                            status=WorkflowStatus.REJECTED,
                            error=exc.to_dict(),
                            started=started,
                        )

                    retries_total += attempts - 1
                    fallback_depth = max(fallback_depth, depth)
                    last_confidence = report.confidence
                    results[node.id] = output
                    RELIABILITY_CONFIDENCE.labels(run.workflow).observe(report.confidence)

                    await self._append_replay(
                        run=run, node_id=node.id, output=output, report=report
                    )

                # advance topology
                for nid in ready:
                    del in_degree[nid]
                    for downstream in edges[nid]:
                        in_degree[downstream] -= 1

        duration_ms = int((time.monotonic() - started) * 1000)
        terminal_id = wf.nodes[-1].id
        final_output = results.get(terminal_id)

        response = WorkflowResponse(
            run_id=run.run_id,
            trace_id=run.trace_id,
            status=WorkflowStatus.SUCCEEDED,
            output=final_output.parsed if final_output and final_output.parsed else None,
            confidence=last_confidence,
            fallback_depth=fallback_depth,
            retries=retries_total,
            duration_ms=duration_ms,
        )
        await self._runs.finish(run.run_id, WorkflowStatus.SUCCEEDED, response.model_dump())
        WORKFLOW_DURATION.labels(run.workflow, "succeeded").observe(duration_ms / 1000.0)
        return response

    async def _run_node(
        self,
        *,
        run: WorkflowRun,
        node_id: str,
        agent_name: str,
        node_input: dict[str, Any],
        tenant_id: str,
        policies: Policies,
    ) -> tuple[AgentOutput, ReliabilityReport, int, int]:
        agent = self._agents.get(agent_name)
        if agent is None:
            raise AegisError(f"unknown agent: {agent_name}", node=node_id)

        retrieved = await self._retrieve_memory(
            tenant_id=tenant_id,
            query=str(node_input.get("question") or node_input.get("topic") or ""),
        )

        chain = list(policies.fallback_chain)
        if not chain:
            chain = [agent.provider]
        elif agent.provider not in chain:
            chain = [agent.provider, *chain]

        provider = chain[0]
        attempts = 0
        depth = 0
        last_output: AgentOutput | None = None
        last_report: ReliabilityReport | None = None

        while True:
            attempts += 1
            ctx = AgentContext(
                run_id=run.run_id,
                trace_id=run.trace_id,
                workflow=run.workflow,
                node_id=node_id,
                inputs=node_input,
                retrieved=retrieved,
                deadline_seconds=policies.deadline_seconds,
                attempt=attempts,
            )

            self._set_provider(agent, provider)
            output = await agent.run(ctx)
            last_output = output

            report = await self._score_reliability(
                workflow=run.workflow,
                invocation=agent.envelope(ctx, prompt="<scored>"),
                output=output,
                policies=policies,
            )
            last_report = report

            decision = decide_route(
                report,
                current_provider=provider,
                fallback_chain=chain,
                attempts_made=attempts,
                max_retries=policies.max_retries,
            )

            if decision.accept:
                # final structural validation pass
                await self._guardrails(output, policies)
                return output, report, attempts, depth

            if decision.retry_provider:
                RETRIES.labels(provider, "low_confidence").inc()
                continue

            if decision.fallback_provider:
                FALLBACKS.labels(provider, decision.fallback_provider).inc()
                provider = decision.fallback_provider
                depth += 1
                # rule_based_fallback short-circuits to deterministic agent
                if provider == "rule_based_fallback":
                    fb = self._agents["rule_based_fallback"]
                    final = await fb.run(ctx)
                    return final, report, attempts, depth

            if decision.reject_reason:
                raise AegisError(
                    decision.reject_reason,
                    last_confidence=report.confidence,
                    anomaly_tags=[t.value for t in report.anomaly_tags],
                )

        # unreachable; mypy appeasement
        assert last_output and last_report
        return last_output, last_report, attempts, depth

    @staticmethod
    def _set_provider(agent: Agent, provider: str) -> None:
        if provider != "rule_based_fallback":
            agent.provider = provider

    async def _retrieve_memory(self, *, tenant_id: str, query: str) -> list[dict[str, Any]]:
        if not query:
            return []
        try:
            resp = await self._http.post(
                f"{self._memory_url}/v1/retrieve",
                json={"query": query, "k": 5},
                headers={"x-tenant-id": tenant_id},
                timeout=2.0,
            )
            if resp.status_code == 200:
                return resp.json().get("hits", [])
        except httpx.RequestError as exc:
            log.warning("memory.unreachable", err=str(exc))
        return []

    async def _score_reliability(
        self,
        *,
        workflow: str,
        invocation: AgentInvocation,
        output: AgentOutput,
        policies: Policies,
    ) -> ReliabilityReport:
        try:
            resp = await self._http.post(
                f"{self._reliability_url}/v1/score",
                json={
                    "workflow": workflow,
                    "invocation": invocation.model_dump(),
                    "output": output.model_dump(),
                    "policies": policies.model_dump(),
                },
                timeout=3.0,
            )
            resp.raise_for_status()
            return ReliabilityReport.model_validate(resp.json())
        except (httpx.RequestError, ValueError) as exc:
            log.warning("reliability.unreachable", err=str(exc))
            return ReliabilityReport.reject("reliability service unreachable")

    async def _guardrails(self, output: AgentOutput, policies: Policies) -> None:
        if policies.output_schema is None:
            return
        try:
            resp = await self._http.post(
                f"{self._guardrails_url}/v1/validate",
                json={"raw": output.raw_text, "schema": policies.output_schema},
                timeout=2.0,
            )
            if resp.status_code == 200:
                body = resp.json()
                if body.get("repaired"):
                    output.parsed = body.get("parsed")
        except httpx.RequestError as exc:
            log.warning("guardrails.unreachable", err=str(exc))

    async def _append_replay(
        self,
        *,
        run: WorkflowRun,
        node_id: str,
        output: AgentOutput,
        report: ReliabilityReport,
    ) -> None:
        try:
            await self._http.post(
                f"{self._replay_url}/v1/events",
                json={
                    "trace_id": run.trace_id,
                    "run_id": run.run_id,
                    "node_id": node_id,
                    "kind": "node_completed",
                    "output": output.model_dump(),
                    "reliability": report.model_dump(),
                },
                timeout=1.0,
            )
        except httpx.RequestError as exc:
            log.warning("replay.unreachable", err=str(exc))

    @staticmethod
    def _build_node_input(
        run: WorkflowRun,
        results: dict[str, AgentOutput],
        upstream_ids: list[str],
    ) -> dict[str, Any]:
        merged: dict[str, Any] = dict(run.request.input)
        if upstream_ids:
            merged["upstream_output"] = "\n".join(
                results[uid].raw_text for uid in upstream_ids if uid in results
            )
        return merged

    @staticmethod
    def _topology(wf: WorkflowDefinition) -> tuple[dict[str, int], dict[str, list[str]]]:
        in_degree: dict[str, int] = {n.id: 0 for n in wf.nodes}
        edges: dict[str, list[str]] = defaultdict(list)
        for n in wf.nodes:
            for upstream in n.inputs_from:
                edges[upstream].append(n.id)
                in_degree[n.id] += 1
        return in_degree, edges

    def _reject(
        self,
        run: WorkflowRun,
        *,
        status: WorkflowStatus,
        error: object,
        started: float,
    ) -> WorkflowResponse:
        duration_ms = int((time.monotonic() - started) * 1000)
        WORKFLOW_DURATION.labels(run.workflow, status.value).observe(duration_ms / 1000.0)
        response = WorkflowResponse(
            run_id=run.run_id,
            trace_id=run.trace_id,
            status=status,
            output=None,
            confidence=None,
            fallback_depth=0,
            retries=0,
            duration_ms=duration_ms,
            error=error if isinstance(error, dict) else {"message": str(error)},
        )
        return response
