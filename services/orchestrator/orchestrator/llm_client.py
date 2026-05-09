"""Provider-agnostic LLM client. Each registered provider goes through its own circuit breaker.

Two providers ship by default:
    - `mock`     : deterministic, used in tests and the default local stack.
    - `openai`   : real provider client, enabled when OPENAI_API_KEY is set.
The factory lets us swap providers per fallback step without leaking SDK details
into the orchestrator code.
"""

from __future__ import annotations

import abc
import asyncio
import json
import os
import random
from dataclasses import dataclass

import httpx
from aegis_core.circuit_breaker import CircuitBreaker
from aegis_core.errors import ChaosInjection, UpstreamTimeout
from aegis_core.metrics import AGENT_INVOCATIONS, CIRCUIT_STATE, TOKENS
from aegis_core.retry import RetryPolicy, retry_async
from aegis_core.schemas import AgentInvocation, AgentOutput
from aegis_core.timeout import with_timeout


@dataclass
class ProviderConfig:
    name: str
    model: str
    base_url: str | None = None
    api_key_env: str | None = None
    chaos_url: str | None = None


class LLMProvider(abc.ABC):
    name: str
    model: str

    @abc.abstractmethod
    async def invoke(self, invocation: AgentInvocation) -> AgentOutput: ...


class MockProvider(LLMProvider):
    """Deterministic-ish provider used in dev and tests.

    It returns structured JSON shaped like a planner/executor would. A small
    amount of injected variance lets us exercise the reliability engine.
    """

    def __init__(self, name: str = "mock", model: str = "mock-1") -> None:
        self.name = name
        self.model = model

    async def invoke(self, invocation: AgentInvocation) -> AgentOutput:
        await asyncio.sleep(random.uniform(0.05, 0.15))

        # Simulate occasional malformed JSON to exercise the guardrail repair path.
        if random.random() < 0.1:
            raw = '{"answer": "unterminated string'
            return AgentOutput(
                agent_id=invocation.agent_id,
                raw_text=raw,
                tokens_in=len(invocation.prompt.split()),
                tokens_out=10,
                latency_ms=int(random.uniform(50, 150)),
                finish_reason="length",
            )

        body = {
            "answer": f"deterministic answer for {invocation.kind.value}",
            "reasoning": "synthetic reasoning trace",
            "citations": [c.get("id") for c in invocation.retrieved_context[:3]],
        }
        raw = json.dumps(body)
        return AgentOutput(
            agent_id=invocation.agent_id,
            raw_text=raw,
            parsed=body,
            tokens_in=len(invocation.prompt.split()),
            tokens_out=len(raw.split()),
            latency_ms=int(random.uniform(50, 150)),
            finish_reason="stop",
        )


class OpenAIProvider(LLMProvider):
    def __init__(self, model: str, api_key: str, base_url: str = "https://api.openai.com/v1"):
        self.name = "openai"
        self.model = model
        self._api_key = api_key
        self._base_url = base_url

    async def invoke(self, invocation: AgentInvocation) -> AgentOutput:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=2.0)) as client:
            resp = await client.post(
                f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": "Return JSON only."},
                        {"role": "user", "content": invocation.prompt},
                    ],
                    "temperature": 0.2,
                    "response_format": {"type": "json_object"},
                },
            )
        if resp.status_code >= 500:
            raise UpstreamTimeout(f"openai {resp.status_code}", status=resp.status_code)
        body = resp.json()
        text = body["choices"][0]["message"]["content"]
        usage = body.get("usage", {})
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        return AgentOutput(
            agent_id=invocation.agent_id,
            raw_text=text,
            parsed=parsed,
            tokens_in=int(usage.get("prompt_tokens", 0)),
            tokens_out=int(usage.get("completion_tokens", 0)),
            latency_ms=0,
            finish_reason=body["choices"][0].get("finish_reason"),
        )


_STATE_TO_GAUGE = {"closed": 0.0, "half_open": 1.0, "open": 2.0}


class LLMClient:
    """Coordinator: picks a provider, guards it with a breaker, applies retries."""

    def __init__(self, configs: list[ProviderConfig], chaos_url: str | None = None) -> None:
        self._providers: dict[str, LLMProvider] = {}
        self._breakers: dict[str, CircuitBreaker] = {}
        self._chaos_url = chaos_url

        for cfg in configs:
            if cfg.name == "mock":
                provider: LLMProvider = MockProvider(name=cfg.name, model=cfg.model)
            elif cfg.name == "openai":
                key = os.environ.get(cfg.api_key_env or "OPENAI_API_KEY", "")
                if not key:
                    continue
                provider = OpenAIProvider(model=cfg.model, api_key=key)
            else:
                continue
            self._providers[cfg.name] = provider
            self._breakers[cfg.name] = CircuitBreaker(name=cfg.name)

    def has(self, name: str) -> bool:
        return name in self._providers

    def names(self) -> list[str]:
        return list(self._providers.keys())

    async def invoke(
        self,
        provider_name: str,
        invocation: AgentInvocation,
        *,
        timeout_seconds: float,
        retry_policy: RetryPolicy | None = None,
    ) -> AgentOutput:
        provider = self._providers[provider_name]
        breaker = self._breakers[provider_name]

        await breaker.guard()

        async def _once() -> AgentOutput:
            await self._maybe_inject_chaos(provider_name)
            try:
                output = await with_timeout(
                    provider.invoke(invocation),
                    timeout_seconds,
                    what=f"{provider_name}.invoke",
                )
            except Exception:
                await breaker.record(ok=False)
                CIRCUIT_STATE.labels(provider_name, provider.model).set(
                    _STATE_TO_GAUGE[breaker.state.value]
                )
                AGENT_INVOCATIONS.labels(invocation.agent_id, provider_name, "error").inc()
                raise
            await breaker.record(ok=True)
            CIRCUIT_STATE.labels(provider_name, provider.model).set(
                _STATE_TO_GAUGE[breaker.state.value]
            )
            AGENT_INVOCATIONS.labels(invocation.agent_id, provider_name, "ok").inc()
            TOKENS.labels(provider_name, "in").inc(output.tokens_in)
            TOKENS.labels(provider_name, "out").inc(output.tokens_out)
            return output

        if retry_policy is None:
            return await _once()
        return await retry_async(_once, retry_policy)

    async def _maybe_inject_chaos(self, provider_name: str) -> None:
        if not self._chaos_url:
            return
        try:
            async with httpx.AsyncClient(timeout=0.25) as client:
                resp = await client.get(f"{self._chaos_url}/v1/chaos/decide/{provider_name}")
                if resp.status_code == 200 and resp.json().get("inject"):
                    raise ChaosInjection(
                        f"chaos injection for {provider_name}",
                        scenario=resp.json().get("scenario"),
                    )
        except httpx.RequestError:
            return  # chaos service down - fail open

    def breaker_state(self, provider_name: str) -> dict[str, object] | None:
        breaker = self._breakers.get(provider_name)
        return breaker.snapshot() if breaker else None
