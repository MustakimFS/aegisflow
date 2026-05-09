"""Retry policy behavior tests."""

from __future__ import annotations

import asyncio

import pytest
from aegis_core.errors import CircuitOpenError, UpstreamTimeout
from aegis_core.retry import RetryPolicy, retry_async


@pytest.mark.asyncio
async def test_succeeds_on_first_attempt() -> None:
    calls = 0

    async def op() -> str:
        nonlocal calls
        calls += 1
        return "ok"

    result = await retry_async(op, RetryPolicy(max_attempts=3))
    assert result == "ok"
    assert calls == 1


@pytest.mark.asyncio
async def test_retries_then_succeeds() -> None:
    calls = 0

    async def op() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise UpstreamTimeout("flaky")
        return "ok"

    result = await retry_async(op, RetryPolicy(max_attempts=5, base_delay=0.001))
    assert result == "ok"
    assert calls == 3


@pytest.mark.asyncio
async def test_raises_after_max_attempts() -> None:
    async def op() -> str:
        raise UpstreamTimeout("nope")

    with pytest.raises(UpstreamTimeout):
        await retry_async(op, RetryPolicy(max_attempts=3, base_delay=0.001))


@pytest.mark.asyncio
async def test_circuit_open_is_not_retried() -> None:
    calls = 0

    async def op() -> str:
        nonlocal calls
        calls += 1
        raise CircuitOpenError("open", circuit="test")

    with pytest.raises(CircuitOpenError):
        await retry_async(op, RetryPolicy(max_attempts=5, base_delay=0.001))
    assert calls == 1


@pytest.mark.asyncio
async def test_unrelated_exception_not_retried() -> None:
    calls = 0

    async def op() -> str:
        nonlocal calls
        calls += 1
        raise ValueError("nope")

    with pytest.raises(ValueError):
        await retry_async(
            op,
            RetryPolicy(max_attempts=5, base_delay=0.001, retry_on=(UpstreamTimeout,)),
        )
    assert calls == 1


@pytest.mark.asyncio
async def test_deadline_short_circuits_retries() -> None:
    calls = 0

    async def op() -> str:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        raise UpstreamTimeout("flaky")

    with pytest.raises(UpstreamTimeout):
        await retry_async(
            op,
            RetryPolicy(max_attempts=10, base_delay=0.05, deadline_seconds=0.06),
        )
    # Should not have run all 10 attempts
    assert calls < 5
