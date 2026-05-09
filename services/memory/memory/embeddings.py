"""Embedding provider abstraction.

Default ships with a deterministic hashing-based embedder so the system runs
without external API keys. Production deployments swap in OpenAI / Cohere
/ local sentence-transformers via the same interface.
"""

from __future__ import annotations

import abc
import hashlib

import numpy as np


class Embedder(abc.ABC):
    dim: int

    @abc.abstractmethod
    async def embed(self, texts: list[str]) -> np.ndarray: ...


class HashingEmbedder(Embedder):
    """Hash-trick embedder. Cheap, deterministic, no network. Good enough for tests + demos.

    Maps tokens into a fixed-dim space via SHA-256 hashing, sums the projected
    vectors, then L2-normalizes. Quality is far worse than a real model, but
    the API contract is identical so swap-in is trivial.
    """

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim

    async def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            for token in t.lower().split():
                h = int(hashlib.sha256(token.encode()).hexdigest()[:8], 16)
                idx = h % self.dim
                sign = 1.0 if (h >> 31) & 1 else -1.0
                out[i, idx] += sign
            norm = np.linalg.norm(out[i])
            if norm > 0:
                out[i] /= norm
        return out
