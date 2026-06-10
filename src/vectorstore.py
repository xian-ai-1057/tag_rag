"""Chroma vectorstore helpers: get_vectorstore, list_sources, fetch_chunks_by_ids.

Clients are lru_cache'd keyed on the current settings values, so Streamlit
reruns and repeated queries reuse one Chroma client / embeddings instance,
while tests that repoint settings (e.g. chroma_dir → tmpdir) get a fresh one.
"""
import logging
from functools import lru_cache

from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings

from src.config import settings

log = logging.getLogger("rag")


@lru_cache(maxsize=4)
def _embeddings_for(model: str, base_url: str, api_key: str) -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        model=model,
        base_url=base_url,
        api_key=api_key,
        check_embedding_ctx_length=False,
    )


@lru_cache(maxsize=4)
def _vectorstore_for(
    collection: str, persist_dir: str, embed_model: str, base_url: str, api_key: str
) -> Chroma:
    return Chroma(
        collection_name=collection,
        embedding_function=_embeddings_for(embed_model, base_url, api_key),
        persist_directory=persist_dir,
        collection_metadata={"hnsw:space": "cosine"},
    )


def get_vectorstore() -> Chroma:
    return _vectorstore_for(
        settings.chroma_collection,
        settings.chroma_dir,
        settings.embed_model,
        settings.ollama_base_url,
        settings.ollama_api_key,
    )


def list_sources() -> list[str]:
    vs = get_vectorstore()
    data = vs.get(include=["metadatas"])
    names = {m.get("filename") for m in (data.get("metadatas") or []) if m and m.get("filename")}
    return sorted(s for s in names if s)


def fetch_chunks_by_ids(chunk_ids: list[str]) -> dict[str, dict]:
    """以穩定 context_id（uuid5('{file_id}:{chunk_index}')）反查 Chroma 內最新原文 + metadata。

    用途：
    - UI 渲染時拿到最新內容（即使文件被重新 ingest 也跟著更新）
    - 對話歷史只需持久化 context_id，需要時再 lookup
    若 id 不在 Chroma（chunk 已被刪），該 key 不會出現在回傳 dict 中。
    """
    if not chunk_ids:
        return {}
    vs = get_vectorstore()
    data = vs.get(ids=chunk_ids, include=["documents", "metadatas"])
    return {
        cid: {"text": doc, "metadata": meta}
        for cid, doc, meta in zip(
            data.get("ids", []), data.get("documents", []), data.get("metadatas", [])
        )
    }
