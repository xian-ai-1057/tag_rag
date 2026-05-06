# Phase 4 Spec: Vector Store (Milvus Lite)

## 目的
把 chunk 與其 metadata（包含完整句子陣列）寫入 Milvus，支援向量檢索。Citation 反查的所有原料（chunk_text、sentences[].char_start/char_end/page、source_path）都存在 metadata JSON。

## 公開介面

```python
# src/vector_store.py
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from src.splitter import Chunk

@dataclass(frozen=True)
class ChunkHit:
    chunk_id: int                 # 與 Chunk.chunk_id 相同（doc 內 0-indexed）
    doc_id: str
    score: float                  # similarity 分數（cosine / IP；越大越相關）
    chunk_text: str
    char_start: int
    char_end: int
    sentences: list[dict]         # 已序列化的 Sentence dict：{sid, text, char_start, char_end, page}
    source_path: str
    doc_title: str | None         # 預留欄位，目前等於 doc_id

class VectorStore:
    def __init__(
        self,
        uri: str = "./milvus.db",
        collection: str = "tag_rag",
        dim: int = 1024,
    ) -> None: ...

    def upsert(self, chunks: list[Chunk], embeddings: np.ndarray, source_paths: dict[str, str] | None = None) -> None:
        """Insert or replace chunks. Same (doc_id, chunk_id) is treated as upsert.
        source_paths: optional override doc_id -> source_path.
        """
        ...

    def search(self, query_embedding: np.ndarray, k: int = 5) -> list[ChunkHit]:
        """Return top-k. query_embedding shape (dim,) or (1, dim)."""
        ...

    def reset(self) -> None:
        """Drop and recreate the collection."""
        ...
```

## Milvus Schema
- 主鍵 `pk` (INT64, autoid=False) ：用 `hash((doc_id, chunk_id))` 或 `doc_id` 字串編碼成穩定整數（例如 `mmh3.hash64` 取一支，並可控）；簡單作法是 `doc_id_hash << 32 | chunk_id`，其中 `doc_id_hash = zlib.crc32(doc_id.encode()) & 0xFFFFFFFF`
- `vector` FLOAT_VECTOR dim=1024
- `doc_id` VARCHAR max_length=128
- `chunk_id` INT64
- `metadata` JSON

Index：`HNSW`（M=16, efConstruction=64），metric `IP`（向量已 L2 normalized → IP = cosine）。

## 行為規範

### `__init__`
- `MilvusClient(uri)`，若 uri 是檔案路徑且不存在自動建立（Milvus Lite 行為）
- 若 collection 不存在 → 自動建立（schema 如上）
- 若存在但 dim 不一致 → 拋 `RuntimeError`

### `upsert(chunks, embeddings, source_paths=None)`
- 對每個 `(chunk, vector)` pair：
  - `pk = (crc32(doc_id) << 32) | chunk_id`
  - `metadata = {chunk_text, char_start, char_end, sentences: [...], source_path, doc_title}`
  - `sentences` 是 list of dict（把 Sentence dataclass 用 `dataclasses.asdict` 轉成 dict）
- 用 Milvus 的 `upsert` API（先 delete by pk 再 insert，Milvus Lite 支援 upsert）
- `embeddings.shape[0]` 必須等於 `len(chunks)`，否則拋 `ValueError`
- 空 list → no-op

### `search(query_embedding, k)`
- 接受 1D 或 2D；轉成 1D
- 呼叫 `client.search(collection, data=[vec], limit=k, output_fields=[...])`
- 解析回 `ChunkHit` 列表，依 score 由大到小
- 空 collection → 回空 list
- `k <= 0` → `ValueError`

### `reset()`
- `drop_collection` 後重新建

## 不變式
- search 回傳 ChunkHit 的 sentences 陣列順序與 Chunk 寫入時相同
- ChunkHit.chunk_text == 寫入時的 chunk.text
- 多次 upsert 同 (doc_id, chunk_id) 不會產生重複資料

## 驗收標準

實際對 Milvus Lite 跑（無需外部 server，local file）：

1. test_init_creates_collection_when_missing
2. test_init_reuses_existing_collection
3. test_init_dim_mismatch_raises
4. test_upsert_then_search_returns_metadata — 寫入 3 個 chunk → search top-1 → 回傳的 ChunkHit metadata round-trip 完整（chunk_text、sentences、source_path）
5. test_upsert_idempotent — 同樣 chunks 上載兩次，collection 數量不增
6. test_upsert_replaces_on_same_pk — 第二次上載修改 chunk_text → search 回新值
7. test_upsert_length_mismatch_raises_ValueError
8. test_upsert_empty_is_noop
9. test_search_top_k — 寫入 5 個正交 chunk，最像的應排第一
10. test_search_empty_collection_returns_empty
11. test_search_k_zero_or_negative_raises
12. test_reset_clears_collection
13. test_sentences_metadata_round_trip — sentences 內 dict 含 sid/text/char_start/char_end/page，欄位名與型別正確

每個測試用 `tmp_path / "test_milvus.db"` 隔離，避免互相干擾。

## 不在範圍內
- Hybrid search（dense + sparse）
- 多 collection 管理
- Distributed Milvus（只用 Lite）
- 動態 schema 演進
