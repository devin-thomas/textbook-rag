from __future__ import annotations

from collections.abc import Sequence

import httpx
import numpy as np


class EmbeddingError(RuntimeError):
    pass


class OllamaEmbeddingClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        expected_dimension: int,
        *,
        timeout: float = 120.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.expected_dimension = expected_dimension
        self.timeout = timeout
        self._client = client

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self.expected_dimension), dtype=np.float32)
        client = self._client or httpx.Client(timeout=self.timeout)
        close_client = self._client is None
        try:
            response = client.post(
                f"{self.base_url}/api/embed",
                json={"model": self.model, "input": list(texts), "truncate": True},
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise EmbeddingError(f"Ollama embedding request failed: {exc}") from exc
        finally:
            if close_client:
                client.close()
        values = payload.get("embeddings")
        if not isinstance(values, list) or len(values) != len(texts):
            raise EmbeddingError("Ollama returned an unexpected embedding count")
        matrix = np.asarray(values, dtype=np.float32)
        if matrix.ndim != 2 or matrix.shape[1] != self.expected_dimension:
            actual = matrix.shape[1] if matrix.ndim == 2 else "invalid"
            raise EmbeddingError(
                f"embedding dimension mismatch: expected {self.expected_dimension}, got {actual}"
            )
        if not np.isfinite(matrix).all():
            raise EmbeddingError("embedding contains non-finite values")
        return matrix
