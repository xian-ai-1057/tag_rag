"""Backward-compat façade. New code: import from `src.*` directly."""
from src.ingest import ingest_paths
from src.retrieval import RerankedChunk, RetrievedChunk, coerce_reranked, retrieve
from src.rag_chain import RagAnswer, query
from src.vectorstore import fetch_chunks_by_ids, list_sources

__all__ = [
    "ingest_paths", "RetrievedChunk", "RerankedChunk", "coerce_reranked", "retrieve",
    "RagAnswer", "query", "fetch_chunks_by_ids", "list_sources",
]
