"""Circuit breaker behavior tests."""

from __future__ import annotations

import asyncio

import pytest
from aegis_core.circuit_breaker import CircuitBreaker, CircuitState
from aegis_core.errors import CircuitOpenError


@pytest.mark.asyncio
async def test_breaker_starts_closed_and_allows_traffic() -> None:
    cb = CircuitBreaker(name="test", min_samples=5, threshold=0.5)
    assert await cb.allow() is True
    assert cb.state is CircuitState.CLOSED


@pytest.mark.asyncio
async def test_breaker_trips_open_above_threshold() -> None:
    cb = CircuitBreaker(name="test", min_samples=4, threshold=0.5, cooldown_seconds=0.01)
    for _ in range(4):
        await cb.record(ok=False)
    assert cb.state is CircuitState.OPEN

    # Calls should be denied while open
    with pytest.raises(CircuitOpenError):
        await cb.guard()


@pytest.mark.asyncio
async def test_breaker_transitions_to_half_open_after_cooldown() -> None:
    cb = CircuitBreaker(name="test", min_samples=2, threshold=0.5, cooldown_seconds=0.01)
    await cb.record(ok=False)
    await cb.record(ok=False)
    assert cb.state is CircuitState.OPEN

    await asyncio.sleep(0.02)
    assert await cb.allow() is True
    assert cb.state is CircuitState.HALF_OPEN


@pytest.mark.asyncio
async def test_half_open_success_closes_breaker() -> None:
    cb = CircuitBreaker(name="test", min_samples=2, threshold=0.5, cooldown_seconds=0.01)
    await cb.record(ok=False)
    await cb.record(ok=False)
    await asyncio.sleep(0.02)
    await cb.allow()  # → HALF_OPEN
    await cb.record(ok=True)
    assert cb.state is CircuitState.CLOSED


@pytest.mark.asyncio
async def test_half_open_failure_extends_cooldown() -> None:
    cb = CircuitBreaker(
        name="test",
        min_samples=2,
        threshold=0.5,
        cooldown_seconds=0.01,
        cooldown_max_seconds=1.0,
    )
    await cb.record(ok=False)
    await cb.record(ok=False)
    await asyncio.sleep(0.02)
    await cb.allow()  # → HALF_OPEN
    await cb.record(ok=False)
    assert cb.state is CircuitState.OPEN
    snapshot = cb.snapshot()
    # Cooldown should have doubled
    assert snapshot["cooldown_remaining"] > 0.015


@pytest.mark.asyncio
async def test_breaker_below_min_samples_does_not_trip() -> None:
    cb = CircuitBreaker(name="test", min_samples=10, threshold=0.5)
    for _ in range(5):
        await cb.record(ok=False)
    # Only 5 samples, below min_samples=10 → still closed
    assert cb.state is CircuitState.CLOSED
