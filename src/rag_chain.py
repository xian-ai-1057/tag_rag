"""query() orchestrator + RagAnswer / CitedChunkRef DTOs."""
import logging

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field

from src.citation import renumber_and_filter
from src.config import settings
from src.llm import _get_llm
from src.prompts import SYSTEM_PROMPT, _BLOCK_TEMPLATE, _USER_TEMPLATE
from src.retrieval import (
    RerankedChunk,
    RetrievedChunk,
    coerce_reranked,
    retrieve,
    to_retrieved_chunk,
)

log = logging.getLogger("rag")


class CitedChunkRef(BaseModel):
    """供 Spec 103（chat history）持久化用的最小引用 ref。"""

    model_config = ConfigDict(extra="forbid")

    context_id: str = Field(..., description="與 RetrievedChunk.context_id 同")
    display_n: int = Field(..., ge=1, description="UI 顯示用的 [n] 編號（renumber 後）")


class RagAnswer(BaseModel):
    """`query()` 的完整輸出。"""

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


def query(
    question: str,
    reranked: list[dict] | list[RerankedChunk] | None = None,
) -> RagAnswer:
    """產生帶 inline [n] citation 的答案。

    reranked 為 None → 走本地 retrieve()；否則用外部（arrkb）reranked 結果，
    跳過本地檢索。兩條路徑都先正規化為 RerankedChunk，再轉成 RetrievedChunk。
    """
    log.info("=" * 60)
    log.info("[query] >>> %s", question)
    reranked = coerce_reranked(reranked) if reranked is not None else retrieve(question)
    if not reranked:
        log.warning("[query] no chunks (empty knowledge base or empty reranked input)")
        return RagAnswer(
            answer="依現有資料無法回答：知識庫目前是空的，請先在「文件管理」分頁上傳文件。",
            citations=[],
            retrieved=[],
        )
    chunks = [to_retrieved_chunk(r, i + 1) for i, r in enumerate(reranked)]
    context = "\n".join(
        _BLOCK_TEMPLATE.format(n=c.n, filename=c.filename, page=c.page, content=c.content)
        for c in chunks
    )
    user_msg = _USER_TEMPLATE.format(context_blocks=context, question=question)
    log.info("[query] assembled prompt: system=%d chars, user=%d chars",
             len(SYSTEM_PROMPT), len(user_msg))
    log.debug("[query] full user message:\n%s", user_msg)

    llm = _get_llm()
    log.info("[query] calling LLM model=%s temperature=0", settings.llm_model)
    resp = llm.invoke([
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=user_msg),
    ])
    print("\n===\n LLM raw response:", resp, "\n===\n")
    raw_answer = resp.content if isinstance(resp.content, str) else str(resp.content)
    log.info("[query] LLM raw answer (%d chars):\n%s", len(raw_answer), raw_answer)

    final_answer, citations = renumber_and_filter(raw_answer, chunks)
    log.info("[query] final answer after renumber (%d citations: %s):\n%s",
             len(citations), [c.n for c in citations], final_answer)
    return RagAnswer(answer=final_answer, citations=citations, retrieved=chunks)
