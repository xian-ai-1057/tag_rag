"""Phase 0 smoke test: skeleton modules import cleanly."""

import importlib

import pytest


@pytest.mark.parametrize(
    "module",
    [
        "src",
        "src.config",
        "src.loaders",
        "src.splitter",
        "src.embedder",
        "src.vector_store",
        "src.prompt",
        "src.citation_parser",
        "src.llm",
        "src.rag",
    ],
)
def test_module_imports(module: str) -> None:
    importlib.import_module(module)


def test_config_from_env_uses_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "OLLAMA_BASE_URL",
        "OLLAMA_MODEL",
        "OLLAMA_API_KEY",
        "MILVUS_URI",
        "MILVUS_COLLECTION",
        "EMBEDDING_MODEL",
        "EMBEDDING_DIM",
        "TOP_K",
    ):
        monkeypatch.delenv(var, raising=False)

    from src.config import Config

    cfg = Config.from_env()
    assert cfg.embedding_dim == 1024
    assert cfg.top_k == 5
    assert cfg.embedding_model == "BAAI/bge-m3"
    assert cfg.ollama_base_url.endswith("/v1")
