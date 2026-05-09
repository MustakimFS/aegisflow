"""Sliding-window circuit breaker.

The breaker tracks success/failure events inside a rolling time window and
trips OPEN when the failure ratio exceeds a configured threshold over a minimum
sample size. This avoids tripping on a single transient blip while still
reacting quickly under sustained failure.

State machine:

    CLOSED ──(failure_ratio > threshold AND samples >= min_samples)──► OPEN
    OPEN ──(cooldown elapsed)──► HALF_OPEN
    HALF_OPEN ──(probe success)──► CLOSED
    HALF_OPEN ──(probe failure)──► OPEN  (cooldown doubled, capped)
"""

from __future__ import annotations

import asyncio
import collections
import time
from dataclasses import dataclass, field
from enum import StrEnum

from aegis_core.errors import CircuitOpenError


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class _Sample:
    ts: float
    ok: bool


@dataclass
class CircuitBreaker:
    """Per-resource circuit breaker. Safe for concurrent async use."""

    name: str
    threshold: float = 0.5  # failure ratio that trips the breaker
    window_seconds: float = 30.0
    min_samples: int = 10
    cooldown_seconds: float = 15.0
    cooldown_max_seconds: float = 120.0

    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _samples: collections.deque[_Sample] = field(default_factory=collections.deque, init=False)
    _opened_at: float = field(default=0.0, init=False)
    _current_cooldown: float = field(default=0.0, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    @property
    def state(self) -> CircuitState:
        return self._state

    async def allow(self) -> bool:
        """Return True if a call is permitted; transition OPEN→HALF_OPEN if cooldown elapsed."""
        async with self._lock:
            if self._state is CircuitState.OPEN:
                if time.monotonic() - self._opened_at >= self._current_cooldown:
                    self._state = CircuitState.HALF_OPEN
                    return True
                return False
            return True

    async def record(self, ok: bool) -> None:
        """Record the outcome of a call. May trip or close the breaker."""
        now = time.monotonic()
        async with self._lock:
            self._samples.append(_Sample(ts=now, ok=ok))
            self._evict(now)

            if self._state is CircuitState.HALF_OPEN:
                if ok:
                    self._close()
                else:
                    self._open(extend=True)
                return

            if self._state is CircuitState.CLOSED and len(self._samples) >= self.min_samples:
                    failures = sum(1 for s in self._samples if not s.ok)
                    if failures / len(self._samples) >= self.threshold:
                        self._open(extend=False)

    async def guard(self) -> None:
        """Raise CircuitOpenError if the breaker won't allow the call."""
        if not await self.allow():
            raise CircuitOpenError(
                f"circuit '{self.name}' is OPEN",
                circuit=self.name,
                cooldown_remaining=max(
                    0.0, self._current_cooldown - (time.monotonic() - self._opened_at)
                ),
            )

    def _evict(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._samples and self._samples[0].ts < cutoff:
            self._samples.popleft()

    def _open(self, *, extend: bool) -> None:
        self._state = CircuitState.OPEN
        self._opened_at = time.monotonic()
        if extend and self._current_cooldown:
            self._current_cooldown = min(self._current_cooldown * 2, self.cooldown_max_seconds)
        else:
            self._current_cooldown = self.cooldown_seconds
        self._samples.clear()

    def _close(self) -> None:
        self._state = CircuitState.CLOSED
        self._current_cooldown = 0.0
        self._samples.clear()

    def snapshot(self) -> dict[str, object]:
        """For metrics / debug endpoints."""
        return {
            "name": self.name,
            "state": self._state.value,
            "samples": len(self._samples),
            "cooldown_remaining": max(
                0.0, self._current_cooldown - (time.monotonic() - self._opened_at)
            )
            if self._state is CircuitState.OPEN
            else 0.0,
        }
