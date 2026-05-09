"""Deadline-aware timeout helpers.

Workflows carry a deadline; every node downstream gets a *budget* derived
from the time remaining. This avoids the classic mistake where every step
has its own fixed timeout and the total request can take far longer than
the client expects.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TypeVar

from aegis_core.errors import UpstreamTimeout

T = TypeVar("T")

_deadline: ContextVar[float | None] = ContextVar("aegis_deadline", default=None)


@contextmanager
def deadline_budget(seconds: float):  # type: ignore[no-untyped-def]
    """Set an absolute monotonic deadline for the duration of the with block."""
    token = _deadline.set(time.monotonic() + seconds)
    try:
        yield
    finally:
        _deadline.reset(token)


def remaining_budget(default: float = float("inf")) -> float:
    deadline = _deadline.get()
    if deadline is None:
        return default
    return max(0.0, deadline - time.monotonic())


async def with_timeout[T](coro: Awaitable[T], seconds: float, *, what: str = "operation") -> T:
    """Wrap a coroutine with a hard timeout, normalized to UpstreamTimeout."""
    budget = min(seconds, remaining_budget(default=seconds))
    if budget <= 0:
        raise UpstreamTimeout(f"{what}: deadline exhausted before start", what=what)
    try:
        return await asyncio.wait_for(coro, timeout=budget)
    except TimeoutError as exc:
        raise UpstreamTimeout(f"{what}: timed out after {budget:.2f}s", what=what) from exc
