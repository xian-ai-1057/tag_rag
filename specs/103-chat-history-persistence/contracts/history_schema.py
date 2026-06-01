# history_schema — Pydantic v2 Schema
# ---------------------------------------------------------------
# Spec: specs/103-chat-history-persistence/spec.md §4, §6
# Owner: spec-author（由 Phase 0 鎖死，後續 teammate 唯讀）
# ---------------------------------------------------------------
"""SQLite-backed chat history 的 DTO 契約。

Conversation / Message / StoredCitation：對應 SQLite 兩張表
（conversations + messages）的 in-memory representation。

StoredCitation 是「Tier 1 chunk-level inline citation」在持久層的最小資料：
只存 context_id + display_n + score + 短 snapshot；渲染時用
`vectorstore.fetch_chunks_by_ids` 反查最新原文（保持 Tier 1 設計理念）。

Usage:
    from src.history.store import HistoryStore
    from src.history.models import Conversation, Message, StoredCitation

    store = HistoryStore("./data/history.sqlite")
    conv = store.create_conversation(title="銀行業務問答")
    store.add_message(conv.id, role="user", content="信用卡業務概況？")
    store.add_message(
        conv.id, role="assistant", content="...",
        citations=[StoredCitation(context_id="...", display_n=1, score=0.7, snapshot_text="...")],
    )

Fixtures:
    contracts/fixtures/conversation_example.json
    contracts/fixtures/message_example.json
    contracts/fixtures/stored_citation_example.json
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------
# Enums
# ---------------------------------------------------------------

class MessageRole(StrEnum):
    """訊息角色。對應 SQLite messages.role 欄位。"""
    USER = "user"
    ASSISTANT = "assistant"


# ---------------------------------------------------------------
# StoredCitation — 持久化用的最小引用 ref
# ---------------------------------------------------------------

class StoredCitation(BaseModel):
    """訊息引用的單一 chunk 持久化資料。

    上游對齊 Spec 100 `CitedChunkRef`（context_id + display_n），本 schema
    額外加：
      - `score`：debug / 排序用（在 chunks 被刪除後仍可看當時 retrieve 信心）
      - `snapshot_text`：當 chunk 被刪除或被重切（file_id 變了）時的 fallback
                       顯示。長度上限 1000 字元（spec §3.4）。

    UI 渲染時：先用 context_id 反查 `fetch_chunks_by_ids`；查無時 fallback
    顯示 snapshot_text + stale 標籤。

    Acceptance:
        - 對應 spec.md §8 AC #1、#4
        - golden fixture：contracts/fixtures/stored_citation_example.json
    """

    model_config = ConfigDict(extra="forbid")

    context_id: str = Field(..., description="與 RetrievedChunk.context_id 同")
    display_n: int = Field(..., ge=1, description="UI 顯示的 [n]（renumber 後）")
    score: float = Field(..., description="cosine relevance（持久化當時的值）")
    snapshot_text: str = Field(
        ...,
        max_length=1000,
        description="chunk 內文快照；上限 1000 字元（超過由 store 端截斷）",
    )


# ---------------------------------------------------------------
# Message
# ---------------------------------------------------------------

class Message(BaseModel):
    """單則訊息（user 或 assistant）。對應 SQLite messages 表一列。

    `citations` 在 SQLite 內以 JSON 字串存於 messages.citations_json 欄；
    in-memory 為 `list[StoredCitation]`。user 訊息 `citations == []`。

    Acceptance:
        - 對應 spec.md §8 AC #1、#3
        - golden fixture：contracts/fixtures/message_example.json
    """

    model_config = ConfigDict(extra="forbid")

    id: int | None = Field(
        default=None,
        description="DB 自動指派的 PK；create 前為 None",
    )
    conv_id: str = Field(..., description="所屬 conversation id（UUID4）")
    role: MessageRole = Field(..., description="user / assistant")
    content: str = Field(..., description="訊息內文（已 renumber 後的 answer 字串）")
    citations: list[StoredCitation] = Field(
        default_factory=list,
        description="assistant 訊息的引用；user 訊息為空 list",
    )
    created_at: datetime = Field(..., description="UTC 時間戳")


# ---------------------------------------------------------------
# Conversation
# ---------------------------------------------------------------

class Conversation(BaseModel):
    """一段對話的 header。對應 SQLite conversations 表一列。

    Acceptance:
        - 對應 spec.md §8 AC #1、#2、#3
        - golden fixture：contracts/fixtures/conversation_example.json
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="UUID4 字串")
    title: str = Field(
        ...,
        description="對話標題（建立時可由 first user message 截取前 N 字）",
    )
    created_at: datetime = Field(..., description="UTC 時間戳")
