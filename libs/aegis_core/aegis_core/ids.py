"""ID minting helpers. Trace IDs are W3C-compatible 16-byte hex; run/span IDs are ULIDs."""

from __future__ import annotations

import os
import secrets
import time

_ULID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_trace_id() -> str:
    """W3C trace context - 32 lowercase hex chars (16 random bytes)."""
    return secrets.token_hex(16)


def new_span_id() -> str:
    """W3C span ID - 16 lowercase hex chars (8 random bytes)."""
    return secrets.token_hex(8)


def new_run_id() -> str:
    """ULID for workflow runs. Lexicographically sortable by creation time."""
    ts_ms = int(time.time() * 1000)
    ts_part = _encode(ts_ms, 10)
    rand_part = _encode(int.from_bytes(os.urandom(10), "big"), 16)
    return ts_part + rand_part


def _encode(value: int, length: int) -> str:
    chars: list[str] = []
    for _ in range(length):
        value, idx = divmod(value, 32)
        chars.append(_ULID_ALPHABET[idx])
    return "".join(reversed(chars))
