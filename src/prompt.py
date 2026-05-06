"""Citation prompt builder for Phase 5.

Renders retrieved chunks into a Perplexity-style pre-numbered prompt and
provides the system prompt that constrains the LLM to emit ``<CIT>`` tags
that downstream parsers can map back to ``ChunkHit.sentences``.
"""

from __future__ import annotations

from pathlib import Path

from src.vector_store import ChunkHit

CITATION_SYSTEM_PROMPT = """You are a careful research assistant. Answer the user's question USING ONLY the
sources provided below. For every factual claim, wrap it in a citation tag of
the form:

  <CIT c="<chunk_id>" s="<sentence_id>">your phrasing of the claim</CIT>

Citation rules:
- chunk_id and sentence_id MUST refer to a chunk and sentence that actually
  appears in the Sources section.
- For a single supporting sentence: s="3"
- For a contiguous range: s="3-5"
- For multiple non-contiguous sentences from the same chunk: s="1,4"
- If a claim needs evidence from multiple chunks, use multiple <CIT> tags.
- DO NOT invent citations. If the sources do not support an answer, reply:
  "I could not find this in the provided sources." (in the same language as
  the question).
- Use the same language as the question for the answer text.
- Keep claims concise; one <CIT> per claim is preferred."""


def _source_label(hit: ChunkHit) -> str:
    if hit.source_path:
        return Path(hit.source_path).name
    if hit.doc_title:
        return hit.doc_title
    return hit.doc_id


def _first_page(hit: ChunkHit) -> int | None:
    if not hit.sentences:
        return None
    p = hit.sentences[0].get("page")
    return p if isinstance(p, int) else None


def render_chunks_block(chunks: list[ChunkHit]) -> str:
    if not chunks:
        return "(no sources retrieved)"
    blocks = []
    for prompt_chunk_idx, hit in enumerate(chunks):
        source = _source_label(hit)
        page = _first_page(hit)
        if page is not None:
            header = f"[chunk_id={prompt_chunk_idx}] (from {source}, page {page})"
        else:
            header = f"[chunk_id={prompt_chunk_idx}] (from {source})"
        sentences = hit.sentences or []
        if sentences:
            sentence_lines = [
                f"  s{i}: {s['text']}" for i, s in enumerate(sentences)
            ]
        else:
            preview = (hit.chunk_text or "")[:200]
            sentence_lines = [f"  s0: {preview}"]
        blocks.append("\n".join([header, *sentence_lines]))
    return "\n\n".join(blocks)


def build_citation_messages(question: str, chunks: list[ChunkHit]) -> list[dict]:
    user_prompt = f"Sources:\n{render_chunks_block(chunks)}\n\nQuestion: {question}"
    return [
        {"role": "system", "content": CITATION_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
