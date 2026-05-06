"""Tests for src.llm.LLMClient using a fake OpenAI SDK client.

We monkeypatch ``src.llm.OpenAI`` with ``FakeOpenAI`` before instantiating
``LLMClient``. The fake records constructor args and the most recent
``chat.completions.create`` call, and returns a response shaped like the
real SDK (``response.choices[0].message.content``).
"""

from __future__ import annotations

from typing import Any

import pytest

from src.llm import LLMClient


# ---------------------------------------------------------------- fakes


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, parent: "FakeOpenAI") -> None:
        self._parent = parent

    def create(self, *, model: str, messages: list[dict], temperature: float, **kw: Any) -> Any:
        self._parent.last_call = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "kwargs": kw,
        }
        if self._parent.raise_exc is not None:
            raise self._parent.raise_exc
        return _FakeResponse(self._parent.response_content)


class _FakeChat:
    def __init__(self, parent: "FakeOpenAI") -> None:
        self.completions = _FakeCompletions(parent)


class FakeOpenAI:
    """Drop-in replacement for ``openai.OpenAI`` used in tests."""

    instances: list["FakeOpenAI"] = []

    def __init__(self, base_url: str | None = None, api_key: str | None = None, **kw: Any) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.init_kwargs = kw
        self.last_call: dict[str, Any] | None = None
        self.response_content: str = "FAKE_RESPONSE"
        self.raise_exc: BaseException | None = None
        self.chat = _FakeChat(self)
        FakeOpenAI.instances.append(self)


@pytest.fixture(autouse=True)
def _reset_fake_instances() -> None:
    FakeOpenAI.instances.clear()


# ---------------------------------------------------------------- tests


def test_llm_client_init_uses_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.llm.OpenAI", FakeOpenAI)
    LLMClient(base_url="http://x:1234/v1", api_key="k", model="m")
    assert len(FakeOpenAI.instances) == 1
    fake = FakeOpenAI.instances[0]
    assert fake.base_url == "http://x:1234/v1"
    assert fake.api_key == "k"


def test_chat_returns_message_content(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.llm.OpenAI", FakeOpenAI)
    client = LLMClient(base_url="http://x/v1", api_key="k", model="m")
    fake = FakeOpenAI.instances[0]
    fake.response_content = "hello"

    result = client.chat([{"role": "user", "content": "hi"}])
    assert result == "hello"


def test_chat_passes_temperature_and_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.llm.OpenAI", FakeOpenAI)
    client = LLMClient(
        base_url="http://x/v1",
        api_key="k",
        model="qwen2.5:7b",
        temperature=0.0,
    )
    fake = FakeOpenAI.instances[0]
    messages = [{"role": "user", "content": "hi"}]
    client.chat(messages)

    assert fake.last_call is not None
    assert fake.last_call["model"] == "qwen2.5:7b"
    assert fake.last_call["temperature"] == 0.0
    assert fake.last_call["messages"] == messages


def test_chat_propagates_exceptions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.llm.OpenAI", FakeOpenAI)
    client = LLMClient(base_url="http://x/v1", api_key="k", model="m")
    fake = FakeOpenAI.instances[0]
    fake.raise_exc = RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        client.chat([{"role": "user", "content": "hi"}])


def test_default_temperature_is_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.llm.OpenAI", FakeOpenAI)
    # Instantiate WITHOUT passing temperature -> default should be 0.0.
    client = LLMClient(base_url="http://x/v1", api_key="k", model="m")
    fake = FakeOpenAI.instances[0]
    client.chat([{"role": "user", "content": "hi"}])

    assert fake.last_call is not None
    assert fake.last_call["temperature"] == 0.0
