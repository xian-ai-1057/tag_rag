"""Tests for the BGE-M3 embedder wrapper (Phase 3).

Most tests mock out ``FlagEmbedding.BGEM3FlagModel`` so CI does not need
to download the real model. The integration test marked ``slow`` is
skipped by default (see ``pytest.ini``).
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import numpy as np
import pytest

from src import embedder as embedder_module
from src.embedder import Embedder


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _install_fake_flag_embedding(
    monkeypatch: pytest.MonkeyPatch, model_factory
) -> MagicMock:
    """Install a fake ``FlagEmbedding`` module with ``BGEM3FlagModel``.

    ``model_factory`` is a zero-arg callable that returns the mock model
    instance produced when ``BGEM3FlagModel(...)`` is called. The returned
    ``MagicMock`` is the patched ``BGEM3FlagModel`` class itself, so callers
    can inspect ``.call_count`` and ``.call_args``.
    """

    cls_mock = MagicMock(side_effect=lambda *a, **kw: model_factory())

    fake_module = types.ModuleType("FlagEmbedding")
    fake_module.BGEM3FlagModel = cls_mock  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "FlagEmbedding", fake_module)

    # If the embedder module imported BGEM3FlagModel at module level, patch
    # the attribute too so it picks up our mock.
    if hasattr(embedder_module, "BGEM3FlagModel"):
        monkeypatch.setattr(embedder_module, "BGEM3FlagModel", cls_mock)

    return cls_mock


def _model_returning(vectors: np.ndarray) -> MagicMock:
    """Return a mock model whose ``encode`` produces ``{'dense_vecs': vectors}``."""

    model = MagicMock()
    model.encode = MagicMock(return_value={"dense_vecs": vectors})
    return model


# ---------------------------------------------------------------------------
# Unit tests (mocked)
# ---------------------------------------------------------------------------


def test_embed_empty_returns_zero_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    cls_mock = _install_fake_flag_embedding(
        monkeypatch, lambda: _model_returning(np.zeros((0, 1024), dtype=np.float32))
    )

    emb = Embedder()
    out = emb.embed([])

    assert isinstance(out, np.ndarray)
    assert out.shape == (0, 1024)
    # Empty input must NOT trigger the heavy model load.
    assert cls_mock.call_count == 0


def test_embed_returns_correct_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_vecs = np.tile(
        np.linspace(0.1, 1.0, 1024, dtype=np.float32), (3, 1)
    )
    _install_fake_flag_embedding(
        monkeypatch, lambda: _model_returning(fake_vecs)
    )

    emb = Embedder()
    out = emb.embed(["a", "b", "c"])

    assert out.shape == (3, 1024)


def test_embed_normalizes_vectors(monkeypatch: pytest.MonkeyPatch) -> None:
    # Each row has L2 norm 2.0 (every element = 2/sqrt(1024)).
    val = 2.0 / np.sqrt(1024)
    raw = np.full((4, 1024), val, dtype=np.float32)
    norms_before = np.linalg.norm(raw, axis=1)
    np.testing.assert_allclose(norms_before, np.full(4, 2.0), atol=1e-5)

    _install_fake_flag_embedding(monkeypatch, lambda: _model_returning(raw))

    emb = Embedder()
    out = emb.embed(["w", "x", "y", "z"])

    norms = np.linalg.norm(out, axis=1)
    np.testing.assert_allclose(norms, np.ones(4), atol=1e-5)


def test_dim_property_returns_1024_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cls_mock = _install_fake_flag_embedding(
        monkeypatch, lambda: _model_returning(np.zeros((0, 1024), dtype=np.float32))
    )

    emb = Embedder()
    assert emb.dim == 1024
    # Reading ``dim`` should not load the model.
    assert cls_mock.call_count == 0


def test_embedder_lazy_load(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_vecs = np.zeros((1, 1024), dtype=np.float32)
    fake_vecs[0, 0] = 1.0  # Already unit-norm.

    cls_mock = _install_fake_flag_embedding(
        monkeypatch, lambda: _model_returning(fake_vecs)
    )

    emb = Embedder()
    # Construction alone must not load the model.
    assert cls_mock.call_count == 0

    out = emb.embed(["x"])
    assert out.shape == (1, 1024)
    # First embed call triggers the load exactly once.
    assert cls_mock.call_count == 1

    # A second embed call should reuse the loaded model (no re-load).
    emb.embed(["y"])
    assert cls_mock.call_count == 1


def test_embed_dtype_is_float32(monkeypatch: pytest.MonkeyPatch) -> None:
    # Provide float64 input on purpose; the embedder should still return float32.
    raw = np.full((2, 1024), 0.5, dtype=np.float64)
    _install_fake_flag_embedding(monkeypatch, lambda: _model_returning(raw))

    emb = Embedder()
    out = emb.embed(["a", "b"])

    assert out.dtype == np.float32


# ---------------------------------------------------------------------------
# Slow integration smoke test (skipped by default)
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_embedder_real_load_smoke() -> None:
    pytest.importorskip("FlagEmbedding")

    emb = Embedder()
    vecs = emb.embed(
        [
            "The cat sat on the mat.",
            "A feline rested on the rug.",
        ]
    )

    assert vecs.shape == (2, 1024)
    assert vecs.dtype == np.float32

    # Both vectors should be unit-norm.
    norms = np.linalg.norm(vecs, axis=1)
    np.testing.assert_allclose(norms, np.ones(2), atol=1e-3)

    # Semantically related sentences should have a high cosine similarity;
    # because vectors are unit-norm, dot product equals cosine similarity.
    sim = float(np.dot(vecs[0], vecs[1]))
    assert sim > 0.5, f"expected related sentences to have sim>0.5, got {sim}"
