"""Thin LLM client for Phase 5.

Uses the OpenAI Python SDK pointed at an Ollama-compatible base URL by
default. The :class:`LLMClient` wrapper exists so the rest of the system
can swap in vLLM, OpenAI proper, or any other compatible endpoint with
no further changes.
"""

from __future__ import annotations

from openai import OpenAI


class LLMClient:
    def __init__(
        self,
        base_url: str = "http://localhost:11434/v1",
        api_key: str = "ollama",
        model: str = "qwen2.5:7b",
        temperature: float = 0.0,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self._client = OpenAI(base_url=base_url, api_key=api_key)

    def chat(self, messages: list[dict]) -> str:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
        )
        return response.choices[0].message.content
