"""Settings singleton loaded from environment / .env file."""
import logging

from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger("rag")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_api_key: str = "ollama"
    llm_model: str = "gemma4:e4b"
    embed_model: str = "bge-m3:latest"
    chroma_dir: str = "./data/chroma"
    chroma_collection: str = "tag_rag_docs"
    top_k: int = 5
    chunk_size: int = 512
    chunk_overlap: int = 128
    history_db_path: str = "./data/history.sqlite"


settings = Settings()
log.info(
    "[config] llm=%s embed=%s chroma_dir=%s top_k=%d chunk=%d/%d",
    settings.llm_model,
    settings.embed_model,
    settings.chroma_dir,
    settings.top_k,
    settings.chunk_size,
    settings.chunk_overlap,
)
