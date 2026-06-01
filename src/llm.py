"""LLM factory — returns a configured ChatOpenAI instance pointing at Ollama."""
from langchain_openai import ChatOpenAI

from src.config import settings


def _get_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.llm_model,
        base_url=settings.ollama_base_url,
        api_key=settings.ollama_api_key,
        temperature=0,
    )
