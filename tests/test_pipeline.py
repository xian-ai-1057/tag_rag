"""End-to-end tests for the Phase 7 RAG pipeline.

These tests use a real Milvus Lite VectorStore (in tmp_path) plus real
loader/splitter/chunker/citation_parser code, and stub out only the
Embedder and LLMClient so the suite stays fast and deterministic.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.rag import RAG
from src.vector_store import VectorStore


class FakeEmbedder:
    """Deterministic embedder. Produces unit one-hot vectors keyed by hash(text).

    Matches the public ``Embedder`` shape: ``.dim`` property and
    ``.embed(list[str]) -> np.ndarray`` of shape ``(N, dim)`` float32.
    """

    def __init__(self, dim: int = 8) -> None:
        self._dim = dim
        self.call_count = 0
        self.last_texts: list[str] | None = None

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, texts: list[str]) -> np.ndarray:
        self.call_count += 1
        self.last_texts = list(texts)
        if not texts:
            return np.zeros((0, self._dim), dtype=np.float32)
        v = np.zeros((len(texts), self._dim), dtype=np.float32)
        for i, t in enumerate(texts):
            v[i, hash(t) % self._dim] = 1.0
        return v


class FakeLLM:
    """Captures the messages it received and returns a canned response."""

    def __init__(self, response: str = "No relevant info.") -> None:
        self.response = response
        self.last_messages: list[dict] | None = None
        self.call_count = 0

    def chat(self, messages: list[dict]) -> str:
        self.call_count += 1
        self.last_messages = messages
        return self.response


def _write_sample(tmp_path, name: str = "sample.txt", body: str | None = None):
    if body is None:
        body = (
            "The quick brown fox jumps over the lazy dog. "
            "Pack my box with five dozen liquor jugs. "
            "Sphinx of black quartz, judge my vow. "
            "How vexingly quick daft zebras jump."
        )
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# 1. ingest -> query happy path
# ---------------------------------------------------------------------------
def test_ingest_then_query_with_mocks(tmp_path):
    sample_path = _write_sample(tmp_path)

    vs = VectorStore(uri=str(tmp_path / "m.db"), collection="t1", dim=8)
    emb = FakeEmbedder(dim=8)
    llm = FakeLLM(response='Per source: <CIT c="0" s="0">the answer</CIT>.')

    rag = RAG(embedder=emb, vector_store=vs, llm=llm, top_k=3)

    n = rag.ingest([str(sample_path)])
    assert n > 0

    result = rag.query("What jumps?")

    assert "the answer" in result.clean_answer
    assert "[1]" in result.clean_answer
    assert len(result.citations) == 1
    assert result.citations[0].source_path == str(sample_path.resolve())


# ---------------------------------------------------------------------------
# 2. unsupported formats are skipped, not fatal
# ---------------------------------------------------------------------------
def test_ingest_skips_unsupported_format(tmp_path):
    txt_path = _write_sample(tmp_path, name="ok.txt")
    xyz_path = tmp_path / "weird.xyz"
    xyz_path.write_text("binary-ish nonsense", encoding="utf-8")

    vs = VectorStore(uri=str(tmp_path / "m.db"), collection="t2", dim=8)
    emb = FakeEmbedder(dim=8)
    llm = FakeLLM()

    rag = RAG(embedder=emb, vector_store=vs, llm=llm)

    # Should not raise; .xyz is skipped, .txt is processed.
    n = rag.ingest([str(txt_path), str(xyz_path)])
    assert n > 0


# ---------------------------------------------------------------------------
# 3. ingest returns the chunk count it actually wrote
# ---------------------------------------------------------------------------
def test_ingest_returns_chunk_count(tmp_path):
    # Build a body with many sentences so multiple chunks are produced
    # at small target_chars.
    sentences = [f"Sentence number {i} contains some filler words." for i in range(20)]
    body = " ".join(sentences)
    sample_path = _write_sample(tmp_path, name="long.txt", body=body)

    vs = VectorStore(uri=str(tmp_path / "m.db"), collection="t3", dim=8)
    emb = FakeEmbedder(dim=8)
    llm = FakeLLM()

    rag = RAG(
        embedder=emb,
        vector_store=vs,
        llm=llm,
        target_chars=80,  # force multiple chunks
        overlap_sentences=1,
    )

    n = rag.ingest([str(sample_path)])

    # Embedder.embed gets called once with the full chunk-text list; that
    # call's text count equals the chunks written.
    assert emb.last_texts is not None
    assert n == len(emb.last_texts)
    assert n >= 2  # multi-chunk by construction


# ---------------------------------------------------------------------------
# 4. query with empty collection still hits the LLM
# ---------------------------------------------------------------------------
def test_query_with_empty_collection(tmp_path):
    vs = VectorStore(uri=str(tmp_path / "m.db"), collection="t4", dim=8)
    emb = FakeEmbedder(dim=8)
    llm = FakeLLM(response="I could not find this in the provided sources.")

    rag = RAG(embedder=emb, vector_store=vs, llm=llm, top_k=3)

    result = rag.query("anything?")

    assert llm.last_messages is not None
    assert "could not find" in result.clean_answer.lower()


# ---------------------------------------------------------------------------
# 5. top_k caps the number of chunks the LLM sees
# ---------------------------------------------------------------------------
def test_query_passes_top_k_chunks_to_llm(tmp_path):
    sentences = [
        f"Topic alpha sentence {i} discusses something specific." for i in range(30)
    ]
    body = " ".join(sentences)
    sample_path = _write_sample(tmp_path, name="big.txt", body=body)

    vs = VectorStore(uri=str(tmp_path / "m.db"), collection="t5", dim=8)
    emb = FakeEmbedder(dim=8)
    llm = FakeLLM(response="No citation here.")

    rag = RAG(
        embedder=emb,
        vector_store=vs,
        llm=llm,
        target_chars=60,  # produce many chunks
        overlap_sentences=1,
        top_k=2,
    )

    n_chunks = rag.ingest([str(sample_path)])
    assert n_chunks >= 3  # we need more than top_k for the test to mean anything

    rag.query("What about alpha?")

    assert llm.last_messages is not None
    user_prompt = llm.last_messages[1]["content"]
    occurrences = user_prompt.count("[chunk_id=")
    assert occurrences == 2
