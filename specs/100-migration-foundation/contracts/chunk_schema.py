# chunk_schema — Pydantic v2 Schema
# ---------------------------------------------------------------
# Spec: specs/100-migration-foundation/spec.md §4, §6
# Owner: spec-author（由 Phase 0 鎖死，後續 teammate 唯讀）
# ---------------------------------------------------------------
"""RAG 檢索與作答 DTO。

承接 Tier 1 既有 dataclass（rag.py 的 RetrievedChunk / RagAnswer），
改寫為 Pydantic v2 BaseModel。**欄位語意不變**，僅換型別系統與加上嚴格驗證。

Usage:
    from src.retrieval import RetrievedChunk
    from src.rag_chain import RagAnswer, CitedChunkRef

    chunk = RetrievedChunk.model_validate(json_dict)

Fixtures:
    contracts/fixtures/retrieved_chunk_example.json
    contracts/fixtures/rag_answer_example.json
"""

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------
# RetrievedChunk — 檢索結果單一 chunk
# ---------------------------------------------------------------

class RetrievedChunk(BaseModel):
    """Retriever 回傳的單一檢索結果，同時是 inline `[n]` citation 的物件型式。

    對應 Tier 1 `rag.py` 第 201-209 行 dataclass。對齊舊專案 Milvus schema 欄位命名：
      - `n` 是「display number」，可能被 `citation.renumber_and_filter` 重編
      - `context_id = uuid5(NS, "{file_id}:{chunk_index}")`，與 Chroma 的 primary key 同形（deterministic UUID）
      - `content` 是 snapshot，UI 渲染時優先用 `fetch_chunks_by_ids` 反查最新

    Acceptance:
        - 對應 spec.md §8 AC #1、#2、#5
        - golden fixture：contracts/fixtures/retrieved_chunk_example.json
    """

    model_config = ConfigDict(extra="forbid")

    n: int = Field(..., ge=1, description="顯示編號（renumber 後 1..N）")
    context_id: str = Field(..., description="穩定主鍵 uuid5('{file_id}:{chunk_index}')，與 Chroma PK 同")
    file_id: str = Field(..., description="每檔識別碼 md5(filename)[:10]")
    content: str = Field(..., description="chunk 內文快照（fetch_chunks_by_ids 失敗時的 fallback）")
    filename: str = Field(..., description="來源檔名（含副檔名）；XLSX 為 '{filename}#{sheet_name}'")
    page: int = Field(default=0, ge=0, description="頁碼（非 PDF 為 0）")
    chunk_index: int = Field(..., ge=0, description="該 file_id 內 chunk 序號（0-based）")
    score: float = Field(..., description="相似度分數（cosine relevance）")


# ---------------------------------------------------------------
# CitedChunkRef — 對 Spec 103 暴露的最小引用 ref
# ---------------------------------------------------------------

class CitedChunkRef(BaseModel):
    """供 Spec 103（chat history）持久化用的最小引用 ref。

    Spec 103 的 `StoredCitation` 會擴充本型別（加 snapshot_text 等），但跨 spec
    對齊用的型別名是本檔的 `CitedChunkRef`。
    """

    model_config = ConfigDict(extra="forbid")

    context_id: str = Field(..., description="與 RetrievedChunk.context_id 同")
    display_n: int = Field(..., ge=1, description="UI 顯示用的 [n] 編號（renumber 後）")


# ---------------------------------------------------------------
# RagAnswer — 單次 query 完整輸出
# ---------------------------------------------------------------

class RagAnswer(BaseModel):
    """`rag_chain.query()` 的完整輸出。

    對應 Tier 1 `rag.py` 第 262-266 行 dataclass。

    - `answer`：renumber + filter 後的最終答案字串（已壓雙空白）
    - `citations`：只含被答案實際引用的 chunks（按 1..N 編號）
    - `retrieved`：本次檢索回的全部 chunks（在 renumber 前的原 n=1..k）

    Acceptance:
        - 對應 spec.md §8 AC #1、#3
        - golden fixture：contracts/fixtures/rag_answer_example.json
    """

    model_config = ConfigDict(extra="forbid")

    answer: str = Field(..., description="最終答案（已 renumber，已壓雙空白）")
    citations: list[RetrievedChunk] = Field(
        default_factory=list,
        description="被答案實際引用的 chunks；n 已 renumber 為 1..len(citations)",
    )
    retrieved: list[RetrievedChunk] = Field(
        default_factory=list,
        description="本次 retrieve 全部結果（renumber 前）；長度 ≤ Settings.top_k",
    )
