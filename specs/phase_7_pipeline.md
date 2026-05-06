# Phase 7 Spec: RAG Pipeline + CLI

## 目的
把 Phase 1–6 的元件串起來成一個 `RAG` 物件，並提供兩個 CLI：`scripts/ingest.py`（建索引）與 `scripts/ask.py`（提問）。

## 公開介面

```python
# src/rag.py
from __future__ import annotations
from pathlib import Path

from src.embedder import Embedder
from src.vector_store import VectorStore
from src.llm import LLMClient
from src.citation_parser import AnswerWithCitations

class RAG:
    def __init__(
        self,
        embedder: Embedder | None = None,
        vector_store: VectorStore | None = None,
        llm: LLMClient | None = None,
        target_chars: int = 800,
        overlap_sentences: int = 1,
        top_k: int = 5,
    ) -> None: ...

    def ingest(self, paths: list[str | Path]) -> int:
        """Load + split + chunk + embed + upsert. Return total chunks added."""
        ...

    def query(self, question: str) -> AnswerWithCitations: ...
```

依賴注入：所有元件從 constructor 傳入；若為 None 則使用預設（讀 `Config.from_env()`）。這讓測試可以塞 mock。

## 行為規範

### `ingest(paths)`
1. 對每個 path 呼叫 `load_document` → Document
2. `split_sentences(doc)` → sentences
3. `build_chunks(doc, sentences, target_chars, overlap_sentences)` → chunks
4. 累積所有 chunks 與 source_paths map: `{doc.doc_id: doc.source_path}`
5. `embeddings = embedder.embed([c.text for c in all_chunks])`
6. `vector_store.upsert(all_chunks, embeddings, source_paths=...)`
7. 回傳 `len(all_chunks)`

注意：source_paths map 需要傳給 vector_store.upsert，這樣 ChunkHit 取得到 source_path。

錯誤處理：
- 單一 path 失敗（FileNotFoundError、UnsupportedFormatError） → log warning 跳過該 path，繼續處理其餘
- 全部失敗 → 回傳 0
- 文件 chunks 為 0（空文件）→ 跳過 embed 與 upsert

### `query(question)`
1. `q_emb = embedder.embed([question])[0]`
2. `hits = vector_store.search(q_emb, k=top_k)`
3. `messages = build_citation_messages(question, hits)`
4. `raw = llm.chat(messages)`
5. `return parse_citations(raw, hits)`

若 hits 為空 → 仍進 LLM（system prompt 會指示 LLM 回「找不到」）。

## CLI

### scripts/ingest.py
```
usage: python scripts/ingest.py <path1> [<path2> ...]
```
- 不接受 0 paths → exit 2 並印 usage
- 印出每個檔案的 ingest 結果（檔名 + 寫入 chunks 數）
- 結束時印總 chunks 數

### scripts/ask.py
```
usage: python scripts/ask.py "你的問題"
```
- 沒給 question → exit 2
- 印 clean_answer
- 印 References：每條格式
  ```
  [1] <claim_text>
      ← <basename(source_path)>:<page or "?"> char[<start>:<end>]
        "<sentence_text 截至 200 字>"
  ```

## 驗收標準

`tests/test_pipeline.py`（mock embedder + mock LLM 跑端到端）：

1. test_ingest_then_query_with_mocks — 用 monkeypatch 的 fake Embedder、fake LLMClient、real Milvus Lite VectorStore（在 tmp_path）跑：ingest 一個 sample.txt → query → 驗證回到正確的 source_path 與 sentence_text
2. test_ingest_skips_unsupported_format — 給一個 .xyz 檔 + 一個 .txt 檔；只有 .txt 被處理（warning 不爆）
3. test_ingest_returns_chunk_count — 驗證回傳數
4. test_query_with_empty_collection — 不 ingest 直接 query → LLM 仍被呼叫，回 "找不到" 字樣（用 fake LLM）
5. test_query_passes_top_k_chunks_to_llm — 驗證 LLM 收到的 messages 內 chunk 數 == min(top_k, available)

CLI tests（`tests/test_cli.py`）— 用 subprocess 跑 script：

6. test_ingest_no_args_exits_2 — `python scripts/ingest.py` exit code 2
7. test_ask_no_args_exits_2 — `python scripts/ask.py` exit code 2

（CLI 端到端不在這階段測；需要真 Ollama，留給 Phase 8 手動驗證。）

不變式：
- `RAG.query` 為純查詢，不 mutate vector_store
- 多次 `query` 同一 question + 同一 fake LLM 回相同結果（pure function 串接）

## 不在範圍內
- async / streaming
- 增量 ingest 去重（同一檔案重 ingest 會走 upsert 自動覆蓋）
- 多 collection 切換
