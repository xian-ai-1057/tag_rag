from __future__ import annotations
import warnings
from pathlib import Path
from typing import Iterable

from src.config import Config
from src.loaders import load_document, UnsupportedFormatError
from src.splitter import split_sentences, build_chunks
from src.embedder import Embedder
from src.vector_store import VectorStore
from src.llm import LLMClient
from src.prompt import build_citation_messages
from src.citation_parser import parse_citations, AnswerWithCitations


class RAG:
    def __init__(
        self,
        embedder=None,
        vector_store=None,
        llm=None,
        target_chars: int = 800,
        overlap_sentences: int = 1,
        top_k: int = 5,
    ) -> None:
        cfg = None
        if embedder is None or vector_store is None or llm is None:
            cfg = Config.from_env()
        self.embedder = embedder if embedder is not None else Embedder(model_name=cfg.embedding_model)
        self.vector_store = vector_store if vector_store is not None else VectorStore(uri=cfg.milvus_uri, collection=cfg.milvus_collection, dim=cfg.embedding_dim)
        self.llm = llm if llm is not None else LLMClient(base_url=cfg.ollama_base_url, api_key=cfg.ollama_api_key, model=cfg.ollama_model)
        self.target_chars = target_chars
        self.overlap_sentences = overlap_sentences
        self.top_k = top_k

    def ingest(self, paths: Iterable[str | Path]) -> int:
        all_chunks = []
        source_paths: dict[str, str] = {}
        for path in paths:
            try:
                doc = load_document(path)
            except (FileNotFoundError, UnsupportedFormatError) as e:
                warnings.warn(f"Skipping {path}: {e}")
                continue
            sentences = split_sentences(doc)
            if not sentences:
                continue
            chunks = build_chunks(doc, sentences, target_chars=self.target_chars, overlap_sentences=self.overlap_sentences)
            all_chunks.extend(chunks)
            source_paths[doc.doc_id] = doc.source_path

        if not all_chunks:
            return 0

        texts = [c.text for c in all_chunks]
        embeddings = self.embedder.embed(texts)
        self.vector_store.upsert(all_chunks, embeddings, source_paths=source_paths)
        return len(all_chunks)

    def query(self, question: str) -> AnswerWithCitations:
        q_emb = self.embedder.embed([question])
        hits = self.vector_store.search(q_emb[0], k=self.top_k) if q_emb.shape[0] > 0 else []
        messages = build_citation_messages(question, hits)
        raw = self.llm.chat(messages)
        return parse_citations(raw, hits)
