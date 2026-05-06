from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    ollama_base_url: str
    ollama_model: str
    ollama_api_key: str
    milvus_uri: str
    milvus_collection: str
    embedding_model: str
    embedding_dim: int
    top_k: int

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
            ollama_model=os.getenv("OLLAMA_MODEL", "qwen2.5:7b"),
            ollama_api_key=os.getenv("OLLAMA_API_KEY", "ollama"),
            milvus_uri=os.getenv("MILVUS_URI", "./milvus.db"),
            milvus_collection=os.getenv("MILVUS_COLLECTION", "tag_rag"),
            embedding_model=os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3"),
            embedding_dim=int(os.getenv("EMBEDDING_DIM", "1024")),
            top_k=int(os.getenv("TOP_K", "5")),
        )


PROJECT_ROOT = Path(__file__).resolve().parent.parent
