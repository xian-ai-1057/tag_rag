"""RetrievedChunk DTO (Pydantic v2) and retrieve() function."""
import logging

from pydantic import BaseModel, ConfigDict, Field

from src.config import settings
from src.vectorstore import get_vectorstore

log = logging.getLogger("rag")


class RetrievedChunk(BaseModel):
    """Retriever 回傳的單一檢索結果，同時是 inline [n] citation 的物件型式。"""

    model_config = ConfigDict(extra="forbid")

    n: int = Field(..., ge=1, description="顯示編號（renumber 後 1..N）")
    context_id: str = Field(..., description="穩定主鍵 uuid5('{file_id}:{chunk_index}')，與 Chroma PK 同")
    file_id: str = Field(..., description="每檔識別碼 md5(filename)[:10]")
    content: str = Field(..., description="chunk 內文快照（fetch_chunks_by_ids 失敗時的 fallback）")
    filename: str = Field(..., description="來源檔名（含副檔名）；XLSX 為 '{filename}#{sheet_name}'")
    page: int = Field(default=0, ge=0, description="頁碼（非 PDF 為 0）")
    chunk_index: int = Field(..., ge=0, description="該 file_id 內 chunk 序號（0-based）")
    score: float = Field(..., description="相似度分數（cosine relevance）")


class RerankedKwargs(BaseModel):
    """arrkb 結果中每個 chunk 的 kwargs 區塊。"""

    model_config = ConfigDict(extra="ignore")

    distance: float = 0.0
    relevance_score: float = Field(..., description="rerank 分數（0..1，越高越相關）")


class RerankedChunk(BaseModel):
    """外部 RAG（retrieve + rerank）的輸出契約 — arrkb schema。

    這是 `retrieve()` 的回傳型，也是外部 production RAG 餵進 `query()` 的型別。
    extra="ignore" 容忍 production 多帶欄位；page 為字串以對齊 arrkb 原樣。
    """

    model_config = ConfigDict(extra="ignore")

    context_id: str
    type: str = "chunk"
    content: str
    kb_name: str = ""
    file_id: str = ""
    filename: str = "?"
    page: str = "0"
    kwargs: RerankedKwargs


def coerce_reranked(data: list[dict | RerankedChunk]) -> list[RerankedChunk]:
    """把外部 list[dict]（arrkb data 陣列）正規化為 list[RerankedChunk]。"""
    return [d if isinstance(d, RerankedChunk) else RerankedChunk.model_validate(d) for d in data]


def to_retrieved_chunk(r: RerankedChunk, n: int) -> RetrievedChunk:
    """arrkb RerankedChunk → 內部 citation 工作型別 RetrievedChunk。

    chunk_index arrkb 無此欄，固定 0（僅顯示用）；score 取 rerank 的 relevance_score。
    """
    return RetrievedChunk(
        n=n,
        context_id=r.context_id,
        file_id=r.file_id,
        content=r.content,
        filename=r.filename,
        page=int(r.page or 0),
        chunk_index=0,
        score=r.kwargs.relevance_score,
    )


def _preview(text: str, n: int = 80) -> str:
    t = text.replace("\n", "⏎ ").strip()
    return t if len(t) <= n else t[:n] + "…"


def retrieve(question: str, k: int | None = None) -> list[RerankedChunk]:
    """本地檢索，輸出對齊外部 RAG 的 arrkb schema（模擬 production RAG 輸出）。"""
    k = k or settings.top_k
    log.info("[retrieve] question=%r k=%d", question, k)
    vs = get_vectorstore()
    results = vs.similarity_search_with_relevance_scores(question, k=k)
    print("\n===\n raw Chroma results:", results, "\n===\n")
    chunks = [
        RerankedChunk(
            context_id=doc.metadata.get("context_id", "?"),
            content=doc.page_content,
            kb_name=settings.chroma_collection,
            file_id=doc.metadata.get("file_id", "?"),
            filename=doc.metadata.get("filename", "?"),
            page=str(doc.metadata.get("page", 0)),
            kwargs=RerankedKwargs(distance=1.0 - float(score), relevance_score=float(score)),
        )
        for doc, score in results
    ]

    log.info("[retrieve] got %d chunks", len(chunks))
    for i, c in enumerate(chunks, start=1):
        log.info("  [%d] id=%s relevance=%.3f filename=%s page=%s | %s",
                 i, c.context_id, c.kwargs.relevance_score, c.filename, c.page, _preview(c.content))
    return chunks
