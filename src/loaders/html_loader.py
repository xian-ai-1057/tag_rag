"""HTML loader — strips noise tags, prefers <main>/<article>/<body>, extracts text."""
import logging
from pathlib import Path

from langchain_core.documents import Document

log = logging.getLogger("rag")

NOISE_TAGS = {"script", "style", "nav", "footer", "aside", "header", "iframe", "noscript", "form"}
_HEADING_TAGS = ["h1", "h2", "h3"]


def _extract_section(root) -> str | None:
    for tag in _HEADING_TAGS:
        el = root.find(tag)
        if el and el.get_text(strip=True):
            return el.get_text(strip=True)
    return None


def _make_doc(path: Path, root) -> Document | None:
    text = root.get_text(separator="\n", strip=True)
    if not text:
        return None
    return Document(
        page_content=text,
        metadata={"filename": path.name, "page": 0, "section": _extract_section(root)},
    )


def load(path: Path) -> list[Document]:
    try:
        from bs4 import BeautifulSoup
    except ImportError as e:
        raise ImportError("beautifulsoup4 is required: pip install beautifulsoup4") from e

    try:
        content = path.read_bytes()
        try:
            text_content = content.decode("utf-8")
        except UnicodeDecodeError:
            text_content = content.decode("latin-1")

        soup = BeautifulSoup(text_content, "lxml")
    except Exception as e:
        raise ValueError(f"Failed to parse HTML: {path.name}") from e

    for tag_name in NOISE_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    root = soup.find("main") or soup.find("article") or soup.find("body") or soup

    docs: list[Document] = []
    if root.name == "body":
        articles = root.find_all("article")
        if len(articles) > 1:
            docs = [doc for a in articles if (doc := _make_doc(path, a)) is not None]

    if not docs and (doc := _make_doc(path, root)) is not None:
        docs = [doc]

    log.info("[html_loader] %s → %d document(s)", path.name, len(docs))
    return docs
