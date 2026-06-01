"""Centralized logging configuration for the tag_rag package."""
import logging
import os

_initialized = False


def setup_logging() -> None:
    global _initialized
    if _initialized:
        return
    _initialized = True

    _log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=_log_level,
        format="%(asctime)s [%(levelname)s] %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    for noisy in ("httpx", "urllib3", "openai", "chromadb", "langchain"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
