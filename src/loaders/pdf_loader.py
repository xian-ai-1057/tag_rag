"""PyPDFLoader wrapper for .pdf files."""
from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document


def load_pdf(path: Path) -> list[Document]:
    docs = PyPDFLoader(str(path)).load()
    return docs
