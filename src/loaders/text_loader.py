"""TextLoader wrapper for .md and .txt files."""
from pathlib import Path

from langchain_community.document_loaders import TextLoader
from langchain_core.documents import Document


def load_text(path: Path) -> list[Document]:
    return TextLoader(str(path), encoding="utf-8").load()
