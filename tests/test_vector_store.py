"""Tests for Phase 4: Milvus Lite vector store.

Each test is isolated by writing to a unique ``tmp_path / "test_milvus.db"``
file, so tests don't share state.
"""

from __future__ import annotations

import warnings

import numpy as np
import pytest

from src.loaders import Document  # noqa: F401  (kept per spec import list)
from src.splitter import Chunk, Sentence

# Suppress noisy urllib3 warnings that pymilvus / milvus-lite can emit.
warnings.filterwarnings("ignore", category=DeprecationWarning, module="urllib3")


def _import_vector_store():
    """Import VectorStore + ChunkHit lazily so test COLLECTION succeeds even
    before Dev implements Phase 4 (the stub module exists but lacks symbols).
    Tests still fail at execution time until the implementation lands.
    """

    from src.vector_store import ChunkHit, VectorStore  # noqa: WPS433

    return VectorStore, ChunkHit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_chunk(
    doc_id: str,
    chunk_id: int,
    text: str,
    sentences: list[Sentence] | None = None,
) -> Chunk:
    """Construct a ``Chunk`` directly without going through the splitter."""

    sentences = sentences or [
        Sentence(sid=0, text=text, char_start=0, char_end=len(text), page=None)
    ]
    return Chunk(
        chunk_id=chunk_id,
        doc_id=doc_id,
        text=text,
        char_start=sentences[0].char_start,
        char_end=sentences[-1].char_end,
        sentences=sentences,
    )


def _unit_vec(dim: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(dim).astype(np.float32)
    return v / np.linalg.norm(v)


def _onehot(dim: int, i: int) -> np.ndarray:
    v = np.zeros(dim, dtype=np.float32)
    v[i] = 1.0
    return v


DIM = 8


# ---------------------------------------------------------------------------
# 1. __init__ behavior
# ---------------------------------------------------------------------------


def test_init_creates_collection_when_missing(tmp_path):
    uri = str(tmp_path / "test_milvus.db")
    VectorStore, ChunkHit = _import_vector_store()
    store = VectorStore(uri=uri, collection="t1", dim=DIM)

    # The collection must exist after construction.
    from pymilvus import MilvusClient

    client = MilvusClient(uri=uri)
    assert client.has_collection("t1")


def test_init_reuses_existing_collection(tmp_path):
    uri = str(tmp_path / "test_milvus.db")
    VectorStore, _ = _import_vector_store()

    VectorStore(uri=uri, collection="reused", dim=DIM)
    # Constructing a second time with same uri+name+dim must not raise.
    VectorStore(uri=uri, collection="reused", dim=DIM)


def test_init_dim_mismatch_raises(tmp_path):
    uri = str(tmp_path / "test_milvus.db")
    VectorStore, _ = _import_vector_store()
    VectorStore(uri=uri, collection="dim_check", dim=8)

    with pytest.raises(RuntimeError):
        VectorStore(uri=uri, collection="dim_check", dim=16)


# ---------------------------------------------------------------------------
# 4. upsert + search round-trip
# ---------------------------------------------------------------------------


def test_upsert_then_search_returns_metadata(tmp_path):
    uri = str(tmp_path / "test_milvus.db")
    VectorStore, ChunkHit = _import_vector_store()
    store = VectorStore(uri=uri, collection="rt", dim=DIM)

    chunks = [
        _make_chunk("docA", 0, "first chunk text"),
        _make_chunk("docA", 1, "second chunk text"),
        _make_chunk("docB", 0, "third chunk text"),
    ]
    vectors = np.stack([_unit_vec(DIM, seed=i) for i in range(3)])

    store.upsert(chunks, vectors)

    # Query with the vector for chunk 0; expect chunk 0 to be top hit.
    hits = store.search(vectors[0], k=1)
    assert len(hits) == 1
    hit = hits[0]
    assert isinstance(hit, ChunkHit)
    assert hit.doc_id == "docA"
    assert hit.chunk_id == 0
    assert hit.chunk_text == "first chunk text"
    # source_path round-trips (Chunk doesn't carry it; default is doc_id or "")
    assert isinstance(hit.source_path, str)
    # Sentences round-trip as list[dict] with the expected keys.
    assert isinstance(hit.sentences, list)
    assert len(hit.sentences) == 1
    s = hit.sentences[0]
    assert isinstance(s, dict)
    assert set(["sid", "text", "char_start", "char_end", "page"]).issubset(s.keys())
    assert s["sid"] == 0
    assert s["text"] == "first chunk text"
    assert s["char_start"] == 0
    assert s["char_end"] == len("first chunk text")
    assert s["page"] is None


# ---------------------------------------------------------------------------
# 5. upsert idempotency
# ---------------------------------------------------------------------------


def test_upsert_idempotent(tmp_path):
    uri = str(tmp_path / "test_milvus.db")
    VectorStore, ChunkHit = _import_vector_store()
    store = VectorStore(uri=uri, collection="idem", dim=DIM)

    chunks = [
        _make_chunk("docA", 0, "first"),
        _make_chunk("docA", 1, "second"),
        _make_chunk("docA", 2, "third"),
    ]
    vectors = np.stack([_unit_vec(DIM, seed=i) for i in range(3)])

    store.upsert(chunks, vectors)
    store.upsert(chunks, vectors)

    from pymilvus import MilvusClient

    client = MilvusClient(uri=uri)
    res = client.query(
        collection_name="idem",
        filter="",
        output_fields=["count(*)"],
    )
    # Result is typically [{"count(*)": N}].
    assert res, "expected at least one row in count query result"
    count = res[0].get("count(*)", res[0].get("count", None))
    assert count == 3


# ---------------------------------------------------------------------------
# 6. upsert replaces on same primary key
# ---------------------------------------------------------------------------


def test_upsert_replaces_on_same_pk(tmp_path):
    uri = str(tmp_path / "test_milvus.db")
    VectorStore, ChunkHit = _import_vector_store()
    store = VectorStore(uri=uri, collection="replace", dim=DIM)

    vec = _unit_vec(DIM, seed=42).reshape(1, DIM)

    store.upsert([_make_chunk("A", 0, "orig")], vec)
    store.upsert([_make_chunk("A", 0, "updated")], vec)

    hits = store.search(vec[0], k=1)
    assert len(hits) == 1
    assert hits[0].chunk_text == "updated"


# ---------------------------------------------------------------------------
# 7. upsert length mismatch
# ---------------------------------------------------------------------------


def test_upsert_length_mismatch_raises_ValueError(tmp_path):
    uri = str(tmp_path / "test_milvus.db")
    VectorStore, ChunkHit = _import_vector_store()
    store = VectorStore(uri=uri, collection="lmis", dim=DIM)

    chunks = [
        _make_chunk("A", 0, "a"),
        _make_chunk("A", 1, "b"),
        _make_chunk("A", 2, "c"),
    ]
    vectors = np.stack([_unit_vec(DIM, seed=i) for i in range(2)])  # only 2 rows

    with pytest.raises(ValueError):
        store.upsert(chunks, vectors)


# ---------------------------------------------------------------------------
# 8. upsert empty is no-op
# ---------------------------------------------------------------------------


def test_upsert_empty_is_noop(tmp_path):
    uri = str(tmp_path / "test_milvus.db")
    VectorStore, ChunkHit = _import_vector_store()
    store = VectorStore(uri=uri, collection="empty", dim=DIM)

    # Should not raise.
    store.upsert([], np.zeros((0, DIM), dtype=np.float32))

    # And searching the empty collection returns [].
    hits = store.search(_unit_vec(DIM, seed=0), k=5)
    assert hits == []


# ---------------------------------------------------------------------------
# 9. top-k search ranks the matching chunk first
# ---------------------------------------------------------------------------


def test_search_top_k(tmp_path):
    uri = str(tmp_path / "test_milvus.db")
    VectorStore, ChunkHit = _import_vector_store()
    store = VectorStore(uri=uri, collection="topk", dim=DIM)

    # Five orthogonal one-hot vectors in 8 dims.
    chunks = [_make_chunk("D", i, f"chunk-{i}") for i in range(5)]
    vectors = np.stack([_onehot(DIM, i) for i in range(5)])

    store.upsert(chunks, vectors)

    # Query with the one-hot for chunk 3 -> chunk 3 should be rank 1.
    hits = store.search(_onehot(DIM, 3), k=5)
    assert len(hits) >= 1
    assert hits[0].doc_id == "D"
    assert hits[0].chunk_id == 3
    assert hits[0].chunk_text == "chunk-3"


# ---------------------------------------------------------------------------
# 10. search empty collection
# ---------------------------------------------------------------------------


def test_search_empty_collection_returns_empty(tmp_path):
    uri = str(tmp_path / "test_milvus.db")
    VectorStore, ChunkHit = _import_vector_store()
    store = VectorStore(uri=uri, collection="vacant", dim=DIM)

    hits = store.search(_unit_vec(DIM, seed=0), k=5)
    assert hits == []


# ---------------------------------------------------------------------------
# 11. invalid k
# ---------------------------------------------------------------------------


def test_search_k_zero_or_negative_raises(tmp_path):
    uri = str(tmp_path / "test_milvus.db")
    VectorStore, ChunkHit = _import_vector_store()
    store = VectorStore(uri=uri, collection="kbad", dim=DIM)

    q = _unit_vec(DIM, seed=0)

    with pytest.raises(ValueError):
        store.search(q, k=0)

    with pytest.raises(ValueError):
        store.search(q, k=-1)


# ---------------------------------------------------------------------------
# 12. reset clears collection
# ---------------------------------------------------------------------------


def test_reset_clears_collection(tmp_path):
    uri = str(tmp_path / "test_milvus.db")
    VectorStore, ChunkHit = _import_vector_store()
    store = VectorStore(uri=uri, collection="reset_me", dim=DIM)

    chunks = [
        _make_chunk("R", 0, "alpha"),
        _make_chunk("R", 1, "beta"),
    ]
    vectors = np.stack([_unit_vec(DIM, seed=i) for i in range(2)])
    store.upsert(chunks, vectors)

    # Sanity: data is there.
    pre_hits = store.search(vectors[0], k=2)
    assert len(pre_hits) >= 1

    store.reset()

    # After reset the collection still exists but is empty.
    hits = store.search(vectors[0], k=2)
    assert hits == []


# ---------------------------------------------------------------------------
# 13. sentences round-trip preserves all fields including page
# ---------------------------------------------------------------------------


def test_sentences_metadata_round_trip(tmp_path):
    uri = str(tmp_path / "test_milvus.db")
    VectorStore, ChunkHit = _import_vector_store()
    store = VectorStore(uri=uri, collection="sent", dim=DIM)

    sentences = [
        Sentence(sid=0, text="Hello world.", char_start=0, char_end=12, page=2),
        Sentence(sid=1, text="Second one!", char_start=13, char_end=24, page=2),
    ]
    chunk = _make_chunk(
        "P", 0, "Hello world. Second one!", sentences=sentences
    )
    vec = _unit_vec(DIM, seed=7).reshape(1, DIM)

    store.upsert([chunk], vec)

    hits = store.search(vec[0], k=1)
    assert len(hits) == 1
    hit = hits[0]
    assert len(hit.sentences) == 2

    s0, s1 = hit.sentences
    assert s0["sid"] == 0
    assert s0["text"] == "Hello world."
    assert s0["char_start"] == 0
    assert s0["char_end"] == 12
    assert s0["page"] == 2

    assert s1["sid"] == 1
    assert s1["text"] == "Second one!"
    assert s1["char_start"] == 13
    assert s1["char_end"] == 24
    assert s1["page"] == 2
