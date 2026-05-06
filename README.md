# tag_rag

**Sentence-level Citation RAG MVP** — 一個能讓 LLM 生成的每一個事實聲明（claim）都精準反查回原文具體句子的最小可行 RAG 系統。每個 citation 都附帶：原始檔案路徑、頁碼、char offset 區間、原句完整文字。

整套系統可在純本機環境運行（Ollama + Milvus Lite + BGE-M3），但 LLM client 採 OpenAI 相容介面，因此可隨時換成 vLLM、OpenAI Cloud、Anthropic、或任意 OpenAI 相容服務，**完全不需要改動其他模組**。

---

## Table of Contents

1. [核心理念：為什麼要做 sentence-level citation](#核心理念)
2. [快速開始](#快速開始-quickstart)
3. [Architecture Overview](#architecture-overview)
4. [Function Flow（函式呼叫流程）](#function-flow)
5. [Data Flow（資料結構轉換流程）](#data-flow)
6. [完整端到端範例](#完整端到端範例)
7. [Module Reference](#module-reference)
8. [Configuration](#configuration)
9. [Testing](#testing)
10. [LLM / Embedding / Vector Store Swap](#llm--embedding--vector-store-swap)
11. [Limitations](#limitations)

---

## 核心理念

NotebookLM、Claude Citations API、Perplexity 都把 sentence-level citation 視為核心差異化能力 — 它能大幅降低 hallucination，並讓使用者**親自驗證**每一個答案的來源。本專案以本機 LLM 復現此能力，採用三段式設計：

| 階段 | 技術 | 來源啟發 |
|---|---|---|
| Retrieval pre-numbering | 把每個 chunk 的句子預先用 `s0:`, `s1:` 編號塞進 prompt | Perplexity |
| Tag-based output | 強制 LLM 用 `<CIT c="X" s="Y">claim</CIT>` 包裹每個事實聲明 | Anthropic Citations API |
| Regex parser + 反查 | 把 tag 用 chunk_id / sentence_id 對應回 retrieval hit 內保留的完整 metadata | 本專案 |

**關鍵不變式（invariant）**：從 ingest 到 query，sentence 的 `(char_start, char_end, page)` 三元組必須完整保留。整個 pipeline 的所有設計都圍繞這個不變式而生。

---

## 快速開始 (Quickstart)

```bash
# 1. 安裝依賴
pip install -r requirements.txt
cp .env.example .env

# 2. 啟動本機 LLM（另一個 shell）
ollama pull qwen2.5:7b
ollama serve

# 3. 把文件放進向量庫（支援 PDF / txt / md / html）
python scripts/ingest.py data/sample.pdf data/notes.md

# 4. 提問
python scripts/ask.py "公司去年營收成長多少？"
```

範例輸出：

```
Answer:
營收較去年成長 12% [1]，主要來自雲端業務 [2]。

References:
  [1] 營收成長 12%
      ← annual_report.pdf:page 5 char[1042:1080]
        "營收較去年成長 12%，達到 NT$ 950M。"
  [2] 主要來自雲端業務
      ← annual_report.pdf:page 5 char[1080:1135]
        "雲端服務貢獻了過半的營收增長。"
```

---

## Architecture Overview

```
┌──────────────────── INGEST PIPELINE ────────────────────┐
│                                                          │
│   files       loaders      splitter    embedder  store   │
│   ─────       ───────      ────────    ────────  ─────   │
│   PDF/txt ──► Document ──► Sentence ──► (N,1024) ──► Milvus
│   md/html      + pages       + Chunk     float32   Lite  │
│                                                          │
└──────────────────────────────────────────────────────────┘

┌──────────────────── QUERY PIPELINE ─────────────────────┐
│                                                          │
│   question  embedder    store        prompt     llm      │
│   ────────  ────────    ─────        ──────     ───      │
│   "..."  ──► (1,1024) ──► top-k ──► messages ──► raw     │
│                          ChunkHit   "Sources:..."  text  │
│                          [chunk_id=0]               │    │
│                            s0: ...                  ▼    │
│                            s1: ...           <CIT c="0"  │
│                                                s="1">..  │
│                                              </CIT>      │
│                                                     │    │
│                                                     ▼    │
│                                              citation    │
│                                              parser      │
│                                                     │    │
│                                                     ▼    │
│                                       AnswerWithCitations│
│                                       (clean_answer +    │
│                                        citations[])      │
└──────────────────────────────────────────────────────────┘
```

兩條 pipeline 共用同一組 dataclass — `Document`、`Sentence`、`Chunk`、`ChunkHit`、`Citation`。`sentence` 的中繼資料一路被攜帶到最終的 `Citation`，這就是 sentence-level 反查能成立的關鍵。

---

## Function Flow

### Ingest 函式呼叫鏈（`RAG.ingest`）

```
scripts/ingest.py:main(argv)
  └─► RAG.__init__()                          # src/rag.py:17
        ├─► Config.from_env()                 # src/config.py
        ├─► Embedder(model_name=...)          # 懶載入，第一次 embed 才下載 BGE-M3
        ├─► VectorStore(uri, collection, dim) # 創建或附加到 Milvus collection
        └─► LLMClient(base_url, api_key, ...) # 只是建立 OpenAI client，未連線
  │
  └─► RAG.ingest([path1, path2, ...])         # src/rag.py:36
        for each path:
        │
        ├─► load_document(path)               # src/loaders.py:173
        │     └── 依副檔名 dispatch:
        │         ├── _load_text(p)           # .txt / .md
        │         ├── _load_html(p)           # .html / .htm  (BeautifulSoup)
        │         └── _load_pdf(p)            # .pdf  (pypdf, 累積 PageSpan)
        │     RETURN Document(doc_id, source_path, text, pages)
        │
        ├─► split_sentences(doc)              # src/splitter.py:143
        │     ├── _BOUNDARY_PATTERN.finditer  # CJK 終結符 + 英文 . ! ? …
        │     ├── _is_abbreviation_period     # 過濾 "Dr." "e.g." "et al."
        │     └── _resolve_page               # char_start → page_num (PDF only)
        │     RETURN list[Sentence(sid, text, char_start, char_end, page)]
        │
        ├─► build_chunks(doc, sentences,      # src/splitter.py:229
        │                target_chars=800,
        │                overlap_sentences=1)
        │     └── greedy 累積 sentence 至 ≥ target_chars，再向後 overlap 1 句
        │     RETURN list[Chunk(chunk_id, doc_id, text, char_start, char_end, sentences)]
        │
        ├─► Embedder.embed([c.text for c in chunks])   # src/embedder.py:56
        │     ├── 第一次呼叫：FlagEmbedding.BGEM3FlagModel(...)
        │     ├── model.encode(texts, batch_size=8, max_length=512)
        │     └── L2-normalize  (defensive — Milvus 用 IP 模擬 cosine)
        │     RETURN np.ndarray (N, 1024) float32
        │
        └─► VectorStore.upsert(chunks, embeddings, source_paths)  # vector_store.py:106
              for each (chunk, vec):
              ├── pk = _make_pk(doc_id, chunk_id)    # CRC32 ⊕ chunk_id → 確定性 INT64
              └── metadata JSON =
                    { chunk_text, char_start, char_end,
                      sentences: [asdict(s) ...],     # 攜帶完整 sentence list
                      source_path, doc_title }
              MilvusClient.upsert(rows)              # idempotent — 同 pk 直接覆寫
```

### Query 函式呼叫鏈（`RAG.query`）

```
scripts/ask.py:main(argv)
  └─► RAG.__init__()                          # 同 ingest
  │
  └─► RAG.query(question)                     # src/rag.py:60
        │
        ├─► Embedder.embed([question])        # 一次 embed 一個句子
        │     RETURN np.ndarray (1, 1024)
        │
        ├─► VectorStore.search(q_emb[0], k=top_k)         # vector_store.py:144
        │     └── MilvusClient.search(metric_type=IP)
        │     RETURN list[ChunkHit(chunk_id, doc_id, score,
        │                          chunk_text, char_start, char_end,
        │                          sentences[], source_path, doc_title)]
        │
        ├─► build_citation_messages(question, hits)        # prompt.py:72
        │     ├── render_chunks_block(hits)
        │     │     for prompt_chunk_idx, hit in enumerate(hits):
        │     │       header = "[chunk_id=<idx>] (from file.pdf, page N)"
        │     │       lines  = [ "  s0: ...", "  s1: ...", ... ]
        │     │     ⚠️ 注意：prompt 裡的 chunk_id 是 hits 的 list index,
        │     │              NOT ChunkHit.chunk_id
        │     └── RETURN [ {role:"system", content: CITATION_SYSTEM_PROMPT},
        │                  {role:"user",   content: "Sources:...\n\nQuestion: ..."} ]
        │
        ├─► LLMClient.chat(messages)          # src/llm.py:26
        │     └── OpenAI SDK: client.chat.completions.create(temperature=0.0)
        │     RETURN raw_text
        │       e.g. "營收成長 <CIT c=\"0\" s=\"1\">12%</CIT>，主要來自
        │             <CIT c=\"0\" s=\"2\">雲端業務</CIT>。"
        │
        └─► parse_citations(raw, hits)        # src/citation_parser.py:68
              for each <CIT c="X" s="Y">claim</CIT> match:
              ├── int(X)  → 對應 hits[X]（記得 X 是 list index）
              ├── _expand_sentence_spec(Y)
              │     "3"     → [3]
              │     "3-5"   → [3, 4, 5]
              │     "1,4"   → [1, 4]
              │     "1,3-5" → [1, 3, 4, 5]
              ├── 取 hits[X].sentences[s_id] for s_id in expanded
              ├── 取出 page / char_start / char_end / 原句 text
              └── 把 <CIT>...</CIT> 替換成 "claim [N]"
              RETURN AnswerWithCitations(clean_answer, citations[Citation, ...])
```

---

## Data Flow

下面以一段中英混排文字「逐 step」追蹤資料變形，你可以對照 [完整端到端範例](#完整端到端範例) 看實際數值。

### Step 1 ── File → Document

**INPUT**: `data/notes.md`
```
公司去年營收成長 12%。雲端服務貢獻了過半的營收增長。
Dr. Lee will report next quarter.
```

**OUTPUT**: `Document`
```python
Document(
    doc_id      = "notes",
    source_path = "/home/user/tag_rag/data/notes.md",
    text        = "公司去年營收成長 12%。雲端服務貢獻了過半的營收增長。\nDr. Lee will report next quarter.",
    pages       = None,            # PDF 才會填，此處為 None
)
```

> 若是 PDF，`pages = [PageSpan(page_num=1, char_start=0, char_end=842), PageSpan(page_num=2, char_start=844, char_end=...)]`，每一頁之間會插入 `"\n\n"` 分隔（cursor 累進 +2，但分隔字元不屬於任何 PageSpan）。

### Step 2 ── Document → Sentences

**OUTPUT**: `list[Sentence]`
```python
[
  Sentence(sid=0, text="公司去年營收成長 12%。",     char_start=0,  char_end=12, page=None),
  Sentence(sid=1, text="雲端服務貢獻了過半的營收增長。", char_start=12, char_end=27, page=None),
  Sentence(sid=2, text="Dr. Lee will report next quarter.", char_start=28, char_end=61, page=None),
]
```

關鍵不變式：`doc.text[s.char_start : s.char_end] == s.text`（splitter 內部以 `assert` 檢查）。

注意 `Dr.` 沒有被切斷成兩句 — `_is_abbreviation_period` 過濾掉了。`et al.`、`e.g.`、`i.e.` 同理。

### Step 3 ── Sentences → Chunks

`build_chunks` 以 `target_chars=800` 為門檻 greedy 累積，超過後 flush 成一個 chunk，並 rewind `overlap_sentences=1` 個句子確保語意連續。

**OUTPUT (假設 target_chars=30 以便看見分割)**: `list[Chunk]`
```python
[
  Chunk(
    chunk_id  = 0,
    doc_id    = "notes",
    text      = "公司去年營收成長 12%。雲端服務貢獻了過半的營收增長。",
    char_start= 0,
    char_end  = 27,
    sentences = [Sentence(sid=0, ...), Sentence(sid=1, ...)],
  ),
  Chunk(
    chunk_id  = 1,
    doc_id    = "notes",
    text      = "雲端服務貢獻了過半的營收增長。\nDr. Lee will report next quarter.",
    char_start= 12,
    char_end  = 61,
    sentences = [Sentence(sid=1, ...), Sentence(sid=2, ...)],   # sid=1 是 overlap
  ),
]
```

> ⚠️ overlap 後的 `Sentence` 物件**不重新編號** — `sid` 仍是原 doc 內的位置。`Chunk.sentences[i].sid != i`，這是刻意的設計，方便日後做去重 / 跨 chunk 比對。但 prompt 渲染與 citation 反查時用的是 `Chunk.sentences` 的 list index，跟 `sid` 無關（見 Step 6）。

### Step 4 ── Chunks → Embeddings → Milvus

**Embedder.embed**:
```
input :  ["公司去年營收成長 12%。雲端服務貢獻了過半的營收增長。", "雲端服務..."]
output:  np.ndarray shape=(2, 1024) dtype=float32, L2-normalized
```

**VectorStore.upsert** 寫進 Milvus 的每一 row：
```python
{
  "pk":        4002847317760000000,   # _make_pk("notes", 0) — CRC32 高位 ⊕ chunk_id 低位
  "vector":    [0.0123, -0.0451, ...],     # 1024-dim float
  "doc_id":    "notes",
  "chunk_id":  0,
  "metadata":  {                       # JSON field — 攜帶反查所需的所有資訊
      "chunk_text":  "公司去年營收成長 12%。雲端服務貢獻了過半的營收增長。",
      "char_start":  0,
      "char_end":    27,
      "sentences": [
          {"sid": 0, "text": "公司去年營收成長 12%。",     "char_start": 0,  "char_end": 12, "page": None},
          {"sid": 1, "text": "雲端服務貢獻了過半的營收增長。", "char_start": 12, "char_end": 27, "page": None},
      ],
      "source_path": "/home/user/tag_rag/data/notes.md",
      "doc_title":   "notes",
  },
}
```

> ✅ 因為 `pk` 由 `(doc_id, chunk_id)` 確定性導出，重 ingest 同一份文件會直接覆寫舊 row — upsert 是 idempotent 的。

### Step 5 ── Question → ChunkHit[]

**INPUT**: `question = "公司去年營收成長多少？"`

**Embedder.embed** → `(1, 1024)`
**VectorStore.search(q_emb[0], k=5)** → `list[ChunkHit]`：

```python
[
  ChunkHit(
    chunk_id    = 0,
    doc_id      = "notes",
    score       = 0.871,                                     # IP score (≈ cosine)
    chunk_text  = "公司去年營收成長 12%。雲端服務貢獻了過半的營收增長。",
    char_start  = 0,
    char_end    = 27,
    sentences   = [ {sid:0, text:"...", char_start:0,  char_end:12, page:None},
                    {sid:1, text:"...", char_start:12, char_end:27, page:None} ],
    source_path = "/home/user/tag_rag/data/notes.md",
    doc_title   = "notes",
  ),
  # ... 其他 hits
]
```

### Step 6 ── ChunkHit[] → Prompt Messages

`build_citation_messages` 把 hits **以其在 list 中的位置**重新編號（**不是** `ChunkHit.chunk_id`），這個重編號的索引就是 LLM 將會引用的 `c="..."` 值：

```text
SYSTEM:
You are a careful research assistant. Answer the user's question USING ONLY
the sources provided below. For every factual claim, wrap it in a citation
tag of the form:
  <CIT c="<chunk_id>" s="<sentence_id>">your phrasing of the claim</CIT>
... (略)

USER:
Sources:
[chunk_id=0] (from notes.md)
  s0: 公司去年營收成長 12%。
  s1: 雲端服務貢獻了過半的營收增長。

[chunk_id=1] (from notes.md)
  s0: 雲端服務貢獻了過半的營收增長。
  s1: Dr. Lee will report next quarter.

Question: 公司去年營收成長多少？
```

> 🔑 prompt 裡 `[chunk_id=0]` 表示 `hits[0]`，其底下的 `s0` 表示 `hits[0].sentences[0]`。LLM 不知道 / 不需要知道原 doc 內的 sid。

### Step 7 ── LLM Raw Output → AnswerWithCitations

LLM 原始輸出（`raw`）：
```text
公司去年營收較前年成長 <CIT c="0" s="0">12%</CIT>。其中 <CIT c="0" s="1">主要由雲端服務貢獻</CIT>。
```

`parse_citations(raw, hits)` 一邊掃描 `<CIT>` tag、一邊把 `(c, s)` 反查回 `hits[c].sentences[s]`：

```python
AnswerWithCitations(
  clean_answer = "公司去年營收較前年成長 12% [1]。其中 主要由雲端服務貢獻 [2]。",
  citations = [
    Citation(
      ref_num       = 1,
      claim_text    = "12%",
      chunk_id      = 0,
      sentence_ids  = [0],
      source_path   = "/home/user/tag_rag/data/notes.md",
      doc_id        = "notes",
      doc_title     = "notes",
      page          = None,
      sentence_text = "公司去年營收成長 12%。",
      char_start    = 0,
      char_end      = 12,
    ),
    Citation(
      ref_num       = 2,
      claim_text    = "主要由雲端服務貢獻",
      chunk_id      = 0,
      sentence_ids  = [1],
      ...
      sentence_text = "雲端服務貢獻了過半的營收增長。",
      char_start    = 12,
      char_end      = 27,
    ),
  ],
)
```

**容錯規則**：
- `c` 超出範圍 / `s` 超出範圍 → warn，把 tag 拆掉只保留 claim 文字（不會留下未編號的 `[N]`）
- `s="3-1"`（順序顛倒） → warn 後正規化為 `[1, 2, 3]`
- `s="1,4"` 部分有效 → 取交集，用有效的部分組合 `sentence_text`
- 解析後 `assert "<CIT" not in clean_answer` — 任何 tag 殘留都是 bug

---

## 完整端到端範例

假設 `data/sample.md` 內容如下：

```markdown
# Q1 Earnings

公司去年營收成長 12%。雲端服務貢獻了過半的營收增長。

毛利率維持在 38%，與去年同期持平。
```

執行：

```bash
python scripts/ingest.py data/sample.md
# Output:
#   data/sample.md: 1 chunks
# Total: 1 chunks ingested.

python scripts/ask.py "毛利率變化如何？"
```

中間發生的事（簡化示意）：

1. **load**：得到 `Document(text="# Q1 Earnings\n\n公司去年營收成長 12%。雲端服務...毛利率維持在 38%，與去年同期持平。")`。
2. **split**：得到 4 個 `Sentence`（標題、營收、雲端、毛利率）。
3. **build_chunks**：總長度遠小於 800，所以 1 個 chunk 內含 4 句。
4. **embed**：產生 `(1, 1024)` float32 vector，寫入 Milvus。
5. **query** 時 question embed 後 search → 取回那 1 個 ChunkHit。
6. **prompt** 渲染：
   ```
   [chunk_id=0] (from sample.md)
     s0: # Q1 Earnings
     s1: 公司去年營收成長 12%。
     s2: 雲端服務貢獻了過半的營收增長。
     s3: 毛利率維持在 38%，與去年同期持平。
   ```
7. **LLM 輸出**：
   ```
   <CIT c="0" s="3">毛利率維持在 38%，與去年同期持平</CIT>。
   ```
8. **parse_citations** 反查 `hits[0].sentences[3]`，組裝 `Citation(page=None, char_start=…, char_end=…, sentence_text="毛利率維持在 38%，與去年同期持平。")`。
9. **CLI 輸出**：
   ```
   Answer:
   毛利率維持在 38%，與去年同期持平 [1]。

   References:
     [1] 毛利率維持在 38%，與去年同期持平
         ← sample.md:page ? char[X:Y]
           "毛利率維持在 38%，與去年同期持平。"
   ```

---

## Module Reference

| Module | 主要 API | 不變式 / 注意事項 |
|---|---|---|
| `src/loaders.py` | `load_document(path) → Document` | PDF 才填 `pages`；空文件僅 warn 不 raise |
| `src/splitter.py` | `split_sentences(doc) → list[Sentence]`<br>`build_chunks(doc, sents, target_chars=800, overlap_sentences=1) → list[Chunk]` | `doc.text[s.char_start:s.char_end] == s.text`<br>`Chunk.sentences` 不重編 sid |
| `src/embedder.py` | `Embedder.embed(texts) → np.ndarray (N, 1024)` | 懶載入；輸出已 L2-normalized |
| `src/vector_store.py` | `VectorStore.upsert(chunks, embeddings, source_paths)`<br>`VectorStore.search(q_emb, k) → list[ChunkHit]`<br>`VectorStore.reset()` | PK 確定性導出 → upsert idempotent；不同 dim 直接 raise |
| `src/prompt.py` | `build_citation_messages(question, hits) → messages` | prompt 裡的 `chunk_id` 是 `hits` 的 list index |
| `src/llm.py` | `LLMClient.chat(messages) → str` | OpenAI 相容；預設 `temperature=0.0` |
| `src/citation_parser.py` | `parse_citations(raw, hits) → AnswerWithCitations` | 解析後 `<CIT>` 不能殘留；越界 tag 降級為純文字 |
| `src/rag.py` | `RAG().ingest(paths)` / `RAG().query(question)` | 串聯所有上述模組；測試可直接注入 mock |

### 關鍵 dataclass 一覽

```python
PageSpan(page_num: int, char_start: int, char_end: int)
Document(doc_id: str, source_path: str, text: str, pages: list[PageSpan] | None)
Sentence(sid: int, text: str, char_start: int, char_end: int, page: int | None)
Chunk(chunk_id: int, doc_id: str, text: str, char_start: int, char_end: int, sentences: list[Sentence])
ChunkHit(chunk_id, doc_id, score, chunk_text, char_start, char_end,
         sentences: list[dict], source_path, doc_title)
Citation(ref_num, claim_text, chunk_id, sentence_ids,
         source_path, doc_id, doc_title, page,
         sentence_text, char_start, char_end)
AnswerWithCitations(clean_answer: str, citations: list[Citation])
```

---

## Configuration

`Config.from_env()` 從環境變數（或 `.env`）讀取設定：

| Env | Default | 說明 |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1` | LLM endpoint（OpenAI 相容） |
| `OLLAMA_MODEL` | `qwen2.5:7b` | LLM 模型名稱 |
| `OLLAMA_API_KEY` | `ollama` | API key（Ollama 不檢查，雲端服務需填真值） |
| `MILVUS_URI` | `./milvus.db` | Milvus Lite 檔案路徑或遠端 server URI |
| `MILVUS_COLLECTION` | `tag_rag` | collection 名稱 |
| `EMBEDDING_MODEL` | `BAAI/bge-m3` | embedder 模型 |
| `EMBEDDING_DIM` | `1024` | 必須與 embedding 模型一致；不同 dim 會在 VectorStore 啟動時 raise |
| `TOP_K` | `5` | retrieval 取回的 chunk 數 |

> 想跑單元測試而**不**想下載模型？預設 `pytest` 已 monkeypatch 掉 Embedder / LLMClient，並用 Milvus Lite tmp file。

---

## Testing

```bash
pytest                            # 預設 — 排除 slow，無需網路 / 無需下載模型
pytest -m slow                    # 整合測試 — 真打 BGE-M3 + Ollama
pytest tests/test_splitter.py -v  # 單一階段
pytest tests/test_X.py::test_name # 單一 case
```

`pytest.ini` 已設 `pythonpath = .`，故 `from src.xxx` 直接可用。

100+ unit tests 覆蓋：

- `test_loaders.py` — txt / md / html / PDF 載入、編碼、頁碼累積
- `test_splitter.py` — 中英混排、abbrev 過濾、char-offset 不變式
- `test_chunks.py` — `build_chunks` 的 target / overlap / 邊界
- `test_embedder.py` — 模型 monkeypatch、L2-norm、空輸入
- `test_vector_store.py` — Milvus Lite tmp file、upsert idempotent、dim mismatch
- `test_prompt.py` — 重編號、page label、空 hits 渲染
- `test_llm.py` — OpenAI SDK 呼叫格式、temperature
- `test_citation_parser.py` — single / range / list / 越界 / 顛倒順序 / tag 殘留
- `test_pipeline.py` — `RAG.ingest` + `RAG.query` 全鏈整合
- `test_cli.py` — `scripts/` 入口參數與輸出格式

---

## LLM / Embedding / Vector Store Swap

**換 LLM**（vLLM / OpenAI / Anthropic compatible）：

```python
from src.rag import RAG
from src.llm import LLMClient

rag = RAG(llm=LLMClient(
    base_url="http://your-vllm-server:8000/v1",
    api_key="your-key",
    model="meta-llama/Llama-3.1-70B-Instruct",
))
```

**換 Embedder**（只要實作 `embed(list[str]) → (N, dim) np.ndarray` 即可）：

```python
class MyEmbedder:
    dim = 768
    def embed(self, texts):
        ...

rag = RAG(embedder=MyEmbedder(), ...)
# VectorStore 的 dim 也必須對應
```

**換 Vector Store**（遠端 Milvus Server）：

```bash
export MILVUS_URI=http://milvus.example.com:19530
```

---

## Limitations

| 不做 | 為什麼 / 替代方案 |
|---|---|
| OCR 掃描 PDF | pypdf 沒有文字層時 warn 並跳過。需 OCR 請先 Tesseract / Adobe → 文字層 PDF / txt |
| Word / PPT 直讀 | 請外部轉成 txt / PDF（pandoc、libreoffice） |
| Hybrid retrieval (BM25+dense) | 目前 dense-only。Milvus 2.4 已有 hybrid，後續可加 |
| Multi-turn 對話歷史 | 每次 query 是獨立的；要做請在 caller 端拼 history |
| 前端 UI | CLI only |
| 強制 `<CIT>` 格式遵循 | 8B 等級本機模型對格式遵循度不如 GPT-4 / Claude，輸出飄掉時：①升級到更大模型，或 ②換 Anthropic Citations API |

---

## Project Layout

```
specs/                       # Spec Guardian — 各階段行為契約（spec → tests → impl）
  phase_0_skeleton.md          # 專案骨架
  phase_1_loaders.md           # txt / md / html / PDF
  phase_2_splitter.md          # 中英混排 sentence + abbrev
  phase_3_embedding.md         # BGE-M3 + chunk
  phase_4_vector_store.md      # Milvus Lite + PK + metadata
  phase_5_llm_prompt.md        # prompt 渲染 + LLM client
  phase_6_citation_parser.md   # <CIT> 解析 + 反查
  phase_7_pipeline.md          # RAG 串接
  phase_8_release.md           # 文件與發布
src/                         # 實作
  loaders.py splitter.py embedder.py vector_store.py
  prompt.py llm.py citation_parser.py rag.py config.py
scripts/                     # CLI
  ingest.py  ask.py
tests/                       # 100+ unit tests + 1 integration suite
data/                        # 範例文件（自行放置）
```

開發採 **Spec-Driven Development**：每階段循環 `spec → tests (red) → impl (green) → 驗收`。修改任何模組前請先閱讀 `specs/phase_*.md` — spec 是行為的唯一真實來源。
