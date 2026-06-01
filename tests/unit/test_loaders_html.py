"""Unit tests for src/loaders/html_loader.py."""
import importlib.util
from pathlib import Path

import pytest
from langchain_core.documents import Document

from src.loaders import load_file

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA_PATH = _REPO_ROOT / "specs" / "102-multi-format-loaders" / "contracts" / "loaded_doc_metadata_schema.py"

_HTML_WITH_NOISE = """\
<!DOCTYPE html>
<html>
<head><title>Test Page</title></head>
<body>
  <nav>Navigation Menu</nav>
  <header>Site Header</header>
  <main>
    <h1>Real Content Title</h1>
    <p>Real content paragraph one.</p>
    <p>Real content paragraph two.</p>
  </main>
  <footer>Footer Text</footer>
  <script>alert('js noise')</script>
</body>
</html>
"""

_HTML_MAIN_VS_BODY = """\
<!DOCTYPE html>
<html>
<body>
  <p>Body-only text outside main.</p>
  <main>
    <h1>Main Section</h1>
    <p>Inside main content.</p>
  </main>
</body>
</html>
"""


def _load_metadata_schema():
    spec = importlib.util.spec_from_file_location("loaded_doc_metadata_schema", _SCHEMA_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.LoadedDocMetadata


@pytest.fixture
def html_noise_path(tmp_path):
    p = tmp_path / "tiny.html"
    p.write_text(_HTML_WITH_NOISE, encoding="utf-8")
    return p


@pytest.fixture
def html_main_body_path(tmp_path):
    p = tmp_path / "main_vs_body.html"
    p.write_text(_HTML_MAIN_VS_BODY, encoding="utf-8")
    return p


def test_html_returns_documents(html_noise_path):
    docs = load_file(html_noise_path)
    assert len(docs) >= 1
    assert all(isinstance(d, Document) for d in docs)


def test_html_real_content_present(html_noise_path):
    docs = load_file(html_noise_path)
    all_text = " ".join(d.page_content for d in docs)
    assert "Real content" in all_text


def test_html_noise_removed(html_noise_path):
    docs = load_file(html_noise_path)
    all_text = " ".join(d.page_content for d in docs)
    assert "Navigation" not in all_text, "nav tag content should be removed"
    assert "Footer Text" not in all_text, "footer tag content should be removed"
    assert "js noise" not in all_text, "script tag content should be removed"
    assert "Site Header" not in all_text, "header tag content should be removed"


def test_html_main_priority_over_body(html_main_body_path):
    docs = load_file(html_main_body_path)
    all_text = " ".join(d.page_content for d in docs)
    assert "Inside main content" in all_text
    assert "Body-only text outside main" not in all_text, (
        "Text outside <main> should not be included when <main> exists"
    )


def test_html_section_from_h1(html_noise_path):
    docs = load_file(html_noise_path)
    sections = [d.metadata.get("section") for d in docs]
    assert any(s == "Real Content Title" for s in sections if s), (
        f"Expected section='Real Content Title', got sections={sections}"
    )


def test_html_metadata_schema(html_noise_path):
    LoadedDocMetadata = _load_metadata_schema()
    docs = load_file(html_noise_path)
    for d in docs:
        LoadedDocMetadata.model_validate(d.metadata)


def test_html_filename_is_basename(html_noise_path):
    docs = load_file(html_noise_path)
    for d in docs:
        assert d.metadata["filename"] == html_noise_path.name


def test_html_htm_extension(tmp_path):
    p = tmp_path / "page.htm"
    p.write_text("<html><body><main><p>Hello HTM</p></main></body></html>", encoding="utf-8")
    docs = load_file(p)
    assert len(docs) >= 1
    assert "Hello HTM" in docs[0].page_content
