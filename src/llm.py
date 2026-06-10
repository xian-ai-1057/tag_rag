"""LLM factory — a ChatOpenAI instance pointing at Ollama, cached per settings values
so repeated queries share one client and its connection pool."""
from functools import lru_cache

from langchain_openai import ChatOpenAI

from src.config import settings


@lru_cache(maxsize=4)
def _llm_for(model: str, base_url: str, api_key: str) -> ChatOpenAI:
    return ChatOpenAI(model=model, base_url=base_url, api_key=api_key, temperature=0)


def _get_llm() -> ChatOpenAI:
    return _llm_for(settings.llm_model, settings.ollama_base_url, settings.ollama_api_key)
