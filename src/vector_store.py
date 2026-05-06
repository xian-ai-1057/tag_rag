"""Milvus Lite-backed vector store for Phase 4.

Stores chunks with their embeddings and full metadata (including the
serialized ``Sentence`` array required for citation back-mapping). The
implementation targets Milvus Lite (``MilvusClient`` with a local file
URI) so no external server is required.
"""

from __future__ import annotations

import zlib
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
from pymilvus import DataType, MilvusClient

from src.splitter import Chunk


@dataclass(frozen=True)
class ChunkHit:
    """A single search result with the metadata needed for citation reverse-lookup."""

    chunk_id: int
    doc_id: str
    score: float
    chunk_text: str
    char_start: int
    char_end: int
    sentences: list[dict]
    source_path: str
    doc_title: str | None


def _make_pk(doc_id: str, chunk_id: int) -> int:
    """Return a stable signed-INT64 primary key for ``(doc_id, chunk_id)``.

    ``crc32(doc_id)`` provides 31 high bits (top bit cleared so the result
    fits Milvus' signed INT64) and ``chunk_id`` occupies the low 32 bits.
    """

    h = zlib.crc32(doc_id.encode("utf-8")) & 0x7FFFFFFF
    return (h << 32) | (chunk_id & 0xFFFFFFFF)


class VectorStore:
    """Thin wrapper around ``MilvusClient`` providing the Phase 4 contract."""

    def __init__(
        self,
        uri: str = "./milvus.db",
        collection: str = "tag_rag",
        dim: int = 1024,
    ) -> None:
        self.uri = uri
        self.collection_name = collection
        self.dim = dim
        self._client = MilvusClient(uri)
        if self._client.has_collection(collection):
            existing = self._client.describe_collection(collection)
            existing_dim = self._extract_vector_dim(existing)
            if existing_dim != dim:
                raise RuntimeError(
                    f"Collection {collection!r} has dim {existing_dim}, "
                    f"requested {dim}"
                )
        else:
            self._create_collection()

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _extract_vector_dim(desc: dict[str, Any]) -> int:
        for f in desc.get("fields", []):
            params = f.get("params") or {}
            if "dim" in params:
                return int(params["dim"])
        raise RuntimeError("Could not determine vector dim from describe_collection")

    def _create_collection(self) -> None:
        schema = self._client.create_schema(
            auto_id=False, enable_dynamic_field=False
        )
        schema.add_field("pk", DataType.INT64, is_primary=True)
        schema.add_field("vector", DataType.FLOAT_VECTOR, dim=self.dim)
        schema.add_field("doc_id", DataType.VARCHAR, max_length=128)
        schema.add_field("chunk_id", DataType.INT64)
        schema.add_field("metadata", DataType.JSON)

        index_params = self._client.prepare_index_params()
        # Milvus Lite only supports FLAT / IVF_FLAT / AUTOINDEX. AUTOINDEX
        # picks a sensible default and matches the spec's intent (cosine
        # similarity via IP on L2-normalized vectors).
        index_params.add_index(
            field_name="vector",
            index_type="AUTOINDEX",
            metric_type="IP",
        )
        self._client.create_collection(
            collection_name=self.collection_name,
            schema=schema,
            index_params=index_params,
        )

    # ------------------------------------------------------------------ public
    def upsert(
        self,
        chunks: list[Chunk],
        embeddings: np.ndarray,
        source_paths: dict[str, str] | None = None,
    ) -> None:
        source_paths = source_paths or {}
        if len(chunks) == 0:
            return
        if embeddings.shape[0] != len(chunks):
            raise ValueError(
                f"Got {len(chunks)} chunks but {embeddings.shape[0]} embeddings"
            )

        rows: list[dict[str, Any]] = []
        for chunk, vec in zip(chunks, embeddings):
            pk = _make_pk(chunk.doc_id, chunk.chunk_id)
            metadata = {
                "chunk_text": chunk.text,
                "char_start": chunk.char_start,
                "char_end": chunk.char_end,
                "sentences": [asdict(s) for s in chunk.sentences],
                "source_path": source_paths.get(chunk.doc_id, ""),
                "doc_title": source_paths.get(f"{chunk.doc_id}::title")
                or chunk.doc_id,
            }
            rows.append(
                {
                    "pk": pk,
                    "vector": np.asarray(vec, dtype=np.float32).tolist(),
                    "doc_id": chunk.doc_id,
                    "chunk_id": chunk.chunk_id,
                    "metadata": metadata,
                }
            )

        self._client.upsert(collection_name=self.collection_name, data=rows)

    def search(self, query_embedding: np.ndarray, k: int = 5) -> list[ChunkHit]:
        if k <= 0:
            raise ValueError("k must be positive")
        vec = np.asarray(query_embedding).reshape(-1).astype(np.float32)

        results = self._client.search(
            collection_name=self.collection_name,
            data=[vec.tolist()],
            limit=k,
            output_fields=["doc_id", "chunk_id", "metadata"],
        )

        hits: list[ChunkHit] = []
        if not results or not results[0]:
            return hits

        for hit in results[0]:
            entity = hit["entity"]
            md = entity["metadata"]
            hits.append(
                ChunkHit(
                    chunk_id=int(entity["chunk_id"]),
                    doc_id=entity["doc_id"],
                    score=float(hit["distance"]),
                    chunk_text=md["chunk_text"],
                    char_start=int(md["char_start"]),
                    char_end=int(md["char_end"]),
                    sentences=md["sentences"],
                    source_path=md.get("source_path", ""),
                    doc_title=md.get("doc_title"),
                )
            )
        return hits

    def reset(self) -> None:
        if self._client.has_collection(self.collection_name):
            self._client.drop_collection(self.collection_name)
        self._create_collection()
