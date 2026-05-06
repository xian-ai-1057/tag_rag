# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Sentence-level citation RAG MVP. Each generated claim is traceable back to a specific source sentence (file path, page, char offset, exact text). Runs entirely on local infra (Ollama + Milvus Lite + BGE-M3) but the LLM client is OpenAI-compatible and can be swapped for vLLM / OpenAI / any compatible endpoint without touching other modules.

## Common commands

```bash
pip install -r requirements.txt
cp .env.example .env

# local model (one-time + background)
ollama pull qwen2.5:7b
ollama serve

# CLI
python scripts/ingest.py data/sample.pdf data/notes.md
python scripts/ask.py "your question"

# tests
pytest                       # default — excludes slow integration tests
pytest -m slow               # real BGE-M3 + real Ollama integration
pytest tests/test_X.py -v    # single phase
pytest tests/test_X.py::test_name  # single test
```

`pytest.ini` sets `pythonpath = .` and auto-excludes the `slow` marker. Default suite uses monkeypatched embedder/LLM and a Milvus Lite tmp file — no network or model download required.

## Architecture

Two pipelines share the same data structures:

**Ingest** (`RAG.ingest`, `src/rag.py:36`):
`load_document` → `split_sentences` → `build_chunks` → `Embedder.embed` → `VectorStore.upsert`

**Query** (`RAG.query`, `src/rag.py:60`):
`Embedder.embed(question)` → `VectorStore.search` → `build_citation_messages` → `LLMClient.chat` → `parse_citations` → `AnswerWithCitations`

The citation mechanism is the central architectural concern; the modules below are designed to preserve the metadata it depends on.

### Citation flow (the key invariant)

1. **Loaders** (`src/loaders.py`) emit a `Document` with `text` plus, for PDFs, a `pages: list[PageSpan]` mapping char ranges → 1-indexed page numbers.
2. **Splitter** (`src/splitter.py`) emits `Sentence(sid, text, char_start, char_end, page)` such that `doc.text[char_start:char_end] == text` (asserted). `build_chunks` groups sentences greedily to ~`target_chars` with `overlap_sentences` overlap and reuses sentence objects (does not renumber).
3. **VectorStore** (`src/vector_store.py`) serializes `chunk.sentences` (via `dataclasses.asdict`) into a Milvus JSON metadata field. The PK is a deterministic INT64 from `(doc_id, chunk_id)` via `_make_pk` (CRC32 high bits + chunk_id low bits) — upsert is idempotent. Index uses `AUTOINDEX` + `IP` metric on L2-normalized vectors (cosine via inner product). The constructor refuses to attach to an existing collection with a different `dim`.
4. **Prompt** (`src/prompt.py`) renders retrieval hits as `[chunk_id=N] (from file, page P)` headers followed by per-sentence lines `s0: ...`, `s1: ...`. **Critical**: the `chunk_id` in the prompt is the *position in the hits list*, NOT `ChunkHit.chunk_id`. The system prompt instructs the LLM to wrap every claim in `<CIT c="<chunk_id>" s="<sentence_id_or_range>">claim</CIT>`.
5. **LLM** (`src/llm.py`) is a thin OpenAI-SDK wrapper; `temperature=0.0` by default for citation determinism.
6. **Citation parser** (`src/citation_parser.py`) regex-matches `<CIT>` tags, looks up `chunks[chunk_id].sentences[sid]` to recover full metadata (page, char range, exact text), and produces `AnswerWithCitations(clean_answer, citations)`. `s` may be a single id, range `3-5`, or comma list `1,4`. Out-of-range / malformed tags are warned and dropped (the bare claim text is preserved in the answer); the parser asserts no `<CIT>` leaks into `clean_answer`.

When changing splitter, chunk metadata, or hit serialization, the contract `chunk.sentences[sid]` must keep working for the whole pipeline — citation tests and the parser depend on this round-trip.

### Configuration

`Config.from_env()` (`src/config.py`) reads env vars (defaults in `.env.example`): `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `OLLAMA_API_KEY`, `MILVUS_URI`, `MILVUS_COLLECTION`, `EMBEDDING_MODEL`, `EMBEDDING_DIM`, `TOP_K`. `RAG.__init__` only constructs a `Config` for components left unspecified — tests inject mocks directly.

## Development model: Spec-Driven Development

Each phase has a spec in `specs/phase_*.md` (loaders, splitter, embedding, vector_store, llm_prompt, citation_parser, pipeline, release). Cycle is **spec → tests (red) → impl (green) → acceptance**. When modifying a module, read its phase spec first — the spec is the source of truth for behavioral contracts (e.g. char-offset invariants, abbreviation lists, chunk overlap semantics, PK derivation).

## Out of scope (intentionally not implemented)

- OCR for scanned PDFs (warns and returns empty text)
- Word/PPT direct loading (convert to txt/PDF first)
- Hybrid retrieval (dense-only)
- Multi-turn conversation history
- UI
