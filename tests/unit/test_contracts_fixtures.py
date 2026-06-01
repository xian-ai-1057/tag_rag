"""驗證所有 contracts/fixtures/*.json 通過對應 Pydantic schema 的 model_validate()。

由 contracts-guardian (Phase 1) 維護。新增 fixture 時補進 _FIXTURE_MAP。
"""
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SPECS = REPO_ROOT / "specs"

_FIXTURE_MAP: list[tuple[str, str, str]] = [
    # (schema_path_relative_to_specs, fixture_filename, class_name)
    (
        "100-migration-foundation/contracts/chunk_schema.py",
        "retrieved_chunk_example.json",
        "RetrievedChunk",
    ),
    (
        "100-migration-foundation/contracts/chunk_schema.py",
        "rag_answer_example.json",
        "RagAnswer",
    ),
    (
        "102-multi-format-loaders/contracts/loaded_doc_metadata_schema.py",
        "docx_metadata_example.json",
        "LoadedDocMetadata",
    ),
    (
        "102-multi-format-loaders/contracts/loaded_doc_metadata_schema.py",
        "xlsx_metadata_example.json",
        "LoadedDocMetadata",
    ),
    (
        "102-multi-format-loaders/contracts/loaded_doc_metadata_schema.py",
        "html_metadata_example.json",
        "LoadedDocMetadata",
    ),
    (
        "103-chat-history-persistence/contracts/history_schema.py",
        "conversation_example.json",
        "Conversation",
    ),
    (
        "103-chat-history-persistence/contracts/history_schema.py",
        "message_example.json",
        "Message",
    ),
    (
        "103-chat-history-persistence/contracts/history_schema.py",
        "stored_citation_example.json",
        "StoredCitation",
    ),
    (
        "104-quality-eval-hallucination/contracts/quality_report_schema.py",
        "quality_report_supported_example.json",
        "QualityReport",
    ),
    (
        "104-quality-eval-hallucination/contracts/quality_report_schema.py",
        "quality_report_unsupported_example.json",
        "QualityReport",
    ),
]


def _load_schema(schema_path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(
        f"contract_{schema_path.stem}", schema_path,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_id(val: str) -> str:
    if not isinstance(val, str):
        return str(val)
    # Use spec id prefix + fixture stem for readable test id
    parts = val.split("/")
    if val.endswith(".py"):
        return parts[0].split("-")[0]
    if val.endswith(".json"):
        return Path(val).stem
    return val


@pytest.mark.parametrize(
    "schema_rel, fixture_name, class_name",
    _FIXTURE_MAP,
    ids=[
        f"{row[0].split('/')[0].split('-')[0]}-{Path(row[1]).stem}"
        for row in _FIXTURE_MAP
    ],
)
def test_contract_fixture(schema_rel: str, fixture_name: str, class_name: str) -> None:
    schema_path = SPECS / schema_rel
    fixture_path = schema_path.parent / "fixtures" / fixture_name
    module = _load_schema(schema_path)
    cls = getattr(module, class_name)
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    cls.model_validate(data)
