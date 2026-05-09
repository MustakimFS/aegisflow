"""Token-bucket rate limiter backed by Redis.

Uses a single atomic Lua script so refill, charge, and reservation happen
in one round trip. This avoids the classic split-brain bug where two
gateway pods both see "tokens=1" and both grant the request.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import redis.asyncio as redis

# KEYS[1] = bucket key
# ARGV[1] = capacity, ARGV[2] = refill_rate (per sec), ARGV[3] = now (sec, float), ARGV[4] = cost
_TOKEN_BUCKET_LUA = """
local bucket = redis.call('HMGET', KEYS[1], 'tokens', 'updated_at')
local capacity = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local cost = tonumber(ARGV[4])

local tokens = tonumber(bucket[1])
local updated_at = tonumber(bucket[2])
if tokens == nil then
  tokens = capacity
  updated_at = now
end

local elapsed = math.max(0, now - updated_at)
tokens = math.min(capacity, tokens + elapsed * rate)

local allowed = 0
if tokens >= cost then
  tokens = tokens - cost
  allowed = 1
end

redis.call('HMSET', KEYS[1], 'tokens', tokens, 'updated_at', now)
redis.call('EXPIRE', KEYS[1], math.ceil(capacity / rate) + 60)

return {allowed, tostring(tokens)}
"""


@dataclass
class RateLimiter:
    redis_client: redis.Redis
    capacity: int
    refill_rate: float

    _script_sha: str | None = None

    async def _ensure_loaded(self) -> str:
        if self._script_sha is None:
            self._script_sha = await self.redis_client.script_load(_TOKEN_BUCKET_LUA)
        return self._script_sha

    async def allow(self, key: str, cost: int = 1) -> tuple[bool, float]:
        sha = await self._ensure_loaded()
        result = await self.redis_client.evalsha(
            sha,
            1,
            key,
            self.capacity,
            self.refill_rate,
            time.time(),
            cost,
        )
        allowed = result[0] == 1
        remaining = float(result[1])
        return allowed, remaining
