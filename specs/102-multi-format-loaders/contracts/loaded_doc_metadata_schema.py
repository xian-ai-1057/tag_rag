# loaded_doc_metadata_schema — Pydantic v2 Schema
# ---------------------------------------------------------------
# Spec: specs/102-multi-format-loaders/spec.md §4, §6
# Owner: spec-author（由 Phase 0 鎖死，後續 teammate 唯讀）
# ---------------------------------------------------------------
"""Loader 產出的 LangChain `Document.metadata` 欄位契約。

Tier 1 的 metadata 慣例只有 `filename` + `page`，本 spec 擴充為支援 DOCX 的章節、
XLSX 的工作表 + 列範圍、HTML 的（可選）section。

注意：LangChain `Document.metadata` 本身是 `dict[str, Any]`，本 schema 用來
規範**哪些 key 會被填入**、語意是什麼、Tier 1 之後新增的 loader 必須遵循這份
欄位約定。validate-only，不更動 `Document` 結構本體。

Usage:
    from src.loaders import load_file
    docs = load_file("foo.xlsx")
    for d in docs:
        LoadedDocMetadata.model_validate(d.metadata)  # 守門

Fixtures:
    contracts/fixtures/docx_metadata_example.json
    contracts/fixtures/xlsx_metadata_example.json
    contracts/fixtures/html_metadata_example.json
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class LoadedDocMetadata(BaseModel):
    """LangChain Document.metadata 在本專案內的欄位契約。

    所有 loader（Tier 1 .pdf/.md/.txt 與 Spec 102 .docx/.xlsx/.html）產出的
    `Document.metadata` 必須通過本 schema validate。

    `extra="allow"`：保留 LangChain / chunking 階段可能加上的額外 key
    （如 `file_id` / `chunk_index` / `context_id` 由 `chunking.py` 後續加入；
    PDF loader 自行加的內部 metadata 等）。本 schema 只規範本 spec **承諾填入** 的欄位。

    Acceptance:
        - 對應 spec.md §8 AC #1、#2、#3、#5
        - golden fixtures：
            contracts/fixtures/docx_metadata_example.json
            contracts/fixtures/xlsx_metadata_example.json
            contracts/fixtures/html_metadata_example.json
    """

    model_config = ConfigDict(extra="allow")

    filename: str = Field(
        ...,
        description=(
            "原始檔名（含副檔名）。XLSX 例外：'{filename}#{sheet_name}'，"
            "讓 file_id 自動按 sheet 隔離（與 Tier 1 context_id 規則零特例相容）。"
        ),
    )
    page: int = Field(
        default=0,
        ge=0,
        description="PDF 頁碼（0-based）；非 PDF loader 一律填 0。",
    )
    section: str | None = Field(
        default=None,
        description="DOCX heading 1/2/3 / HTML 最近一層 h1-h3；其他 loader 為 None。",
    )
    sheet: str | None = Field(
        default=None,
        description="XLSX 工作表名稱；其他 loader 為 None。",
    )
    row_range: str | None = Field(
        default=None,
        description=(
            "XLSX row 範圍字串 '{start}-{end}'（1-based、closed-interval、"
            "包含 header row）；其他 loader 為 None。"
        ),
    )
