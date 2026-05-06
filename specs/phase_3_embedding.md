# Phase 3 Spec: Chunk Builder + Embedder

## 目的
1. 把句子組成 chunk（embedding 與 retrieval 的單位），**完整保留 chunk 涵蓋的句子陣列** —— citation 反查需要。
2. 提供 BGE-M3 embedding wrapper（用 OpenAI-compatible 或 FlagEmbedding，先實作 FlagEmbedding 版本，介面可換）。

## 公開介面

```python
# src/splitter.py（追加，不取代既有 Sentence/split_sentences）
from __future__ import annotations
from dataclasses import dataclass

from src.loaders import Document
# Sentence is already defined in this module.

@dataclass(frozen=True)
class Chunk:
    chunk_id: int                # 0-indexed in the document
    doc_id: str
    text: str                    # 直接從 doc.text 切片：text[chunk_char_start:chunk_char_end]
    char_start: int              # in doc.text
    char_end: int                # exclusive
    sentences: list[Sentence]    # 涵蓋的句子（其 sid 與 char offset 仍是相對 doc.text）

def build_chunks(
    doc: Document,
    sentences: list[Sentence],
    target_chars: int = 800,
    overlap_sentences: int = 1,
) -> list[Chunk]: ...
```

```python
# src/embedder.py
from __future__ import annotations
import numpy as np

class Embedder:
    def __init__(self, model_name: str = "BAAI/bge-m3", device: str | None = None) -> None: ...
    def embed(self, texts: list[str]) -> np.ndarray:
        """Return shape (len(texts), dim) float32, L2-normalized."""
        ...
    @property
    def dim(self) -> int: ...
```

## 行為規範

### Chunk 組裝
1. 用句子做單位累積：依序加入句子直到累積字元數 ≥ `target_chars`，封一個 chunk。
2. 下一個 chunk 從「上一個 chunk 結尾往前 `overlap_sentences` 句」開始（提供上下文）。
3. **不切句子中間**：chunk 邊界永遠對齊句子邊界。
4. `chunk.text = doc.text[chunk.char_start:chunk.char_end]`，且 `chunk.char_start = chunk.sentences[0].char_start`、`chunk.char_end = chunk.sentences[-1].char_end`。
5. **chunk 內的 sentence 物件直接重用 split_sentences 回傳的（同 sid、同 offset）**，不要重編號。
6. 空 sentences 列表 → 回傳空 list。
7. 單句超過 `target_chars` → 該句獨立成一個 chunk（不再切割）。

### Embedder
- 預設 `BAAI/bge-m3`，dim=1024。
- 用 `FlagEmbedding.BGEM3FlagModel`，呼叫 `model.encode(texts, batch_size=...)['dense_vecs']`，回傳 numpy float32。
- 回傳前做 L2 normalize（BGE-M3 預設已 normalize；保險起見再算一次）。
- `embed([])` → 回傳 shape `(0, dim)` 的 array。
- `device=None` 自動選（cuda → mps → cpu）。
- 模型載入做成 lazy（首次 `embed` 才載），避免 import 時間。

## 不變式
- 對每個 chunk：`doc.text[chunk.char_start:chunk.char_end] == chunk.text`
- chunk.sentences 順序與 sid 嚴格遞增
- chunks[i].chunk_id = i

## 驗收標準

### Splitter（chunk 部分）
1. 輸入 0 句 → 回 0 chunks
2. chunk text 與 char offset round-trip：`doc.text[c.char_start:c.char_end] == c.text`
3. 連續 chunk 之間有 `overlap_sentences` 句重疊（除非總句數很少）
4. 單句超長 → 該句單獨成 chunk
5. chunk_id 從 0 連續遞增
6. 每個 chunk 至少含一個句子
7. chunk.sentences 全部來自原 sentences 列表（同 sid）

### Embedder
1. **以 mock/單元測試為主**，避免 CI 一定要下載 BGE-M3 模型：
   - `test_embed_empty_returns_zero_rows` — 用 monkeypatch 取代 model
   - `test_embed_returns_correct_shape` — mock model 回固定向量，斷言 shape=(N, 1024)
   - `test_embed_normalizes_vectors` — 給未正規化向量，驗證 L2=1
   - `test_dim_property_returns_1024_default`
2. **可選的 integration test**：標記 `@pytest.mark.slow`，實際載入 BGE-M3 並 embed 一句，驗證 dim=1024、值合理（unit-norm，dot-product 對相似句 > 不相關句）。預設 `pytest` 不跑 slow（用 `-m "not slow"`），需要時 `pytest -m slow`。

## 不在範圍內
- BM25 / hybrid retrieval（dense-only）
- 重新切換 embedding backend 至 sentence-transformers / Ollama（介面留有空間，但本階段只實作 FlagEmbedding）
- Reranker
