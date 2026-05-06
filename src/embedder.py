"""BGE-M3 embedder for Phase 3.

Thin wrapper around ``FlagEmbedding.BGEM3FlagModel`` that lazily loads the
model on first ``embed`` call, returns a ``(N, dim)`` float32 numpy array,
and L2-normalizes the output defensively. See
``specs/phase_3_embedding.md`` for the behavioural contract.
"""

from __future__ import annotations

import numpy as np


class Embedder:
    """Embed texts as dense vectors using BGE-M3."""

    def __init__(
        self, model_name: str = "BAAI/bge-m3", device: str | None = None
    ) -> None:
        self.model_name = model_name
        self.device = device or self._auto_device()
        self._model = None  # lazy
        self._dim = 1024

    @staticmethod
    def _auto_device() -> str:
        try:
            import torch

            if torch.cuda.is_available():
                return "cuda"
            if (
                hasattr(torch.backends, "mps")
                and torch.backends.mps.is_available()
            ):
                return "mps"
        except ImportError:
            pass
        return "cpu"

    @property
    def dim(self) -> int:
        return self._dim

    def _load(self):
        if self._model is None:
            # Import inside _load so tests can monkeypatch
            # ``FlagEmbedding.BGEM3FlagModel`` before instantiation.
            import FlagEmbedding

            self._model = FlagEmbedding.BGEM3FlagModel(
                self.model_name, use_fp16=False, device=self.device
            )
        return self._model

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self._dim), dtype=np.float32)
        model = self._load()
        out = model.encode(texts, batch_size=8, max_length=512)["dense_vecs"]
        arr = np.asarray(out, dtype=np.float32)
        # L2-normalize defensively.
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        arr = arr / norms
        return arr.astype(np.float32, copy=False)
