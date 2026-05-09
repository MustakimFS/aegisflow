"""Retry with full jitter and deadline propagation.

We use *full jitter* (`random() * cap`) rather than equal jitter because it
gives lower variance under high contention - see "Exponential Backoff and
Jitter", AWS Architecture Blog, 2015.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from aegis_core.errors import AegisError, CircuitOpenError, UpstreamTimeout

T = TypeVar("T")

# Errors that should never be retried - they indicate a fast-fail signal.
NON_RETRYABLE: tuple[type[BaseException], ...] = (
    CircuitOpenError,
    KeyboardInterrupt,
    SystemExit,
    asyncio.CancelledError,
)


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay: float = 0.1
    max_delay: float = 5.0
    deadline_seconds: float | None = None
    retry_on: tuple[type[BaseException], ...] = (UpstreamTimeout, ConnectionError, TimeoutError)

    def delay_for_attempt(self, attempt: int) -> float:
        """Full-jitter exponential backoff."""
        cap = min(self.max_delay, self.base_delay * (2 ** (attempt - 1)))
        return random.uniform(0.0, cap)


async def retry_async[T](
    op: Callable[[], Awaitable[T]],
    policy: RetryPolicy,
    *,
    on_retry: Callable[[int, BaseException], None] | None = None,
) -> T:
    """Run `op` under `policy`. Re-raises the last exception if all attempts fail.

    Respects `deadline_seconds`: if the next sleep would push us past the
    deadline, we surface the failure immediately rather than burning the budget.
    """
    deadline = (
        asyncio.get_event_loop().time() + policy.deadline_seconds
        if policy.deadline_seconds is not None
        else None
    )

    last_exc: BaseException | None = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return await op()
        except NON_RETRYABLE:
            raise
        except policy.retry_on as exc:
            last_exc = exc
            if attempt >= policy.max_attempts:
                break
            sleep = policy.delay_for_attempt(attempt)
            if deadline is not None and asyncio.get_event_loop().time() + sleep >= deadline:
                break
            if on_retry is not None:
                on_retry(attempt, exc)
            await asyncio.sleep(sleep)
        except AegisError:
            raise
        except Exception:
            raise

    assert last_exc is not None
    raise last_exc
