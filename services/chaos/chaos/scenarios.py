"""Failure-injection scenarios.

Each scenario is a named distribution of failure modes to inject when active.
The orchestrator's LLM client polls `/v1/chaos/decide/{provider}` before
every invocation; the chaos service rolls dice against the active scenarios
and returns whether to inject (and what kind).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class FailureMode(StrEnum):
    LATENCY = "latency"               # extra sleep before response
    TIMEOUT = "timeout"               # forced TimeoutError
    PROVIDER_5XX = "provider_5xx"     # synthetic 503 from provider
    MALFORMED_JSON = "malformed_json"
    HALLUCINATION = "hallucination"   # plausible-sounding wrong answer
    REFUSAL = "refusal"


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    target_providers: tuple[str, ...]
    failure_mode: FailureMode
    probability: float
    enabled: bool = True


@dataclass
class ScenarioRegistry:
    scenarios: dict[str, Scenario] = field(default_factory=dict)

    def add(self, scenario: Scenario) -> None:
        self.scenarios[scenario.name] = scenario

    def remove(self, name: str) -> None:
        self.scenarios.pop(name, None)

    def for_provider(self, provider: str) -> list[Scenario]:
        return [
            s
            for s in self.scenarios.values()
            if s.enabled and (provider in s.target_providers or "*" in s.target_providers)
        ]

    def list(self) -> list[Scenario]:
        return list(self.scenarios.values())


def builtin_scenarios() -> ScenarioRegistry:
    reg = ScenarioRegistry()
    reg.add(
        Scenario(
            name="primary-blip",
            description="Occasional 5xx from the primary provider - exercises fallback.",
            target_providers=("openai",),
            failure_mode=FailureMode.PROVIDER_5XX,
            probability=0.05,
            enabled=False,
        )
    )
    reg.add(
        Scenario(
            name="json-corruption",
            description="Random malformed JSON to exercise the guardrail repair path.",
            target_providers=("*",),
            failure_mode=FailureMode.MALFORMED_JSON,
            probability=0.1,
            enabled=False,
        )
    )
    reg.add(
        Scenario(
            name="latency-spike",
            description="Adds 2-5s latency to provider calls.",
            target_providers=("*",),
            failure_mode=FailureMode.LATENCY,
            probability=0.2,
            enabled=False,
        )
    )
    return reg
