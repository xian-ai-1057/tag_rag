"""pytest configuration — register custom marks."""
import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "requires_ollama: mark test as requiring a running local Ollama instance"
    )
