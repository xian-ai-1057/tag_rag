# Spec 100 — Migration & Foundation

> 對應重建計畫 §「Spec 100 — Migration & Foundation」、§「Phase 1 — Migration」、§「Tier 1 Completed」。
> 上游：無（Tier 1 既有 `rag.py` / `app.py`）。
> 下游：Spec 102 / 103 / 104 / 105 全部依賴本 spec 拆出來的 `src/*` 模組與 Pydantic v2 DTO。

---

## 1. Context

Tier 1 已驗證的 RAG 端到端能力（chunk-level inline `[n]` citation、重編號、`chunk_id` 反查、Streamlit UI）目前**全部塞在 `rag.py`（350 行）** 與 `app.py`（100 行）兩個 flat 檔。痛點：

1. **無法平行開發**：Phase 2 三個功能（loaders / history / eval）若繼續在 `rag.py` 上加程式碼，三個 teammate 會在同一檔案撞修改；按 agent-teams 規則「兩位 teammate 不可同改一檔案」會被阻塞。
2. **DTO 是 dataclass，無 schema 驗證**：`RetrievedChunk` 與 `RagAnswer` 是 `@dataclass`，下游 Spec 103 要把 citations 落地到 SQLite 之前無法用 `model_validate` 守門；fixtures 與真實 runtime 物件偏離也偵測不到。
3. **`app.py` 直接 `from rag import ...`**：未來 Phase 3 要在 `app.py` 加 sidebar / QualityReport panel，import 面又會擴張，造成 `app.py` 與 `rag.py` 強耦合。

本 spec **只做拆檔 + DTO Pydantic 化 + 補 baseline test**。**不**加任何新功能、**不**改 chunk_id / renumber 演算法、**不**改 prompt 文字。所有 Tier 1 已驗證行為以 byte-identical 為目標保留。

---

## 2. Scope

### In scope

- 把 `rag.py` 拆成 `src/` 下 11 個 module（見 §4.1 檔案地圖）
- 把 `RetrievedChunk` 與 `RagAnswer` 從 `@dataclass` 改成 Pydantic v2 `BaseModel`，欄位語意完全不變
- 新增輕量 DTO `CitedChunkRef`，供 Spec 103 持久化引用時消費
- 把 `rag.py` 改成 **10 行內** 的 façade，re-export 既有公開名稱（讓 `app.py` 一行不改仍能跑）
- 補 5 條 baseline pytest（renumber 基本、renumber 空、chunk_id 穩定、fetch_by_ids 部分命中、e2e smoke）
- 建立 `tests/fixtures/docs/tiny.{pdf,md,txt}` 三個極小 fixture
- 寫 `scripts/regression.sh`：依序跑 unit + integration（不打 Ollama）+ requires_ollama tests
- `contracts/chunk_schema.py` 與兩個 golden fixture 由本 spec author 鎖死，後續 teammate 唯讀

### Out of scope

- **任何新功能**（**第 1 次重複提醒**）：本 spec 純粹 refactor + Pydantic 化
- **改 `chunk_id` 演算法**：`f"{doc_id}:{chunk_index}"` + `doc_id = md5(source)[:10]` 不准改（**第 1 次重複提醒**）
- **改 renumber 演算法**：依答案中首次出現順序重編、編造編號從文字刪除、雙空白壓縮——三項規則 byte-identical 保留（**第 1 次重複提醒**）
- **改 prompt 文字**：`SYSTEM_PROMPT`、`_USER_TEMPLATE`、`_BLOCK_TEMPLATE` 內文一字不改（**第 1 次重複提醒**）
- 新格式 loader（DOCX / XLSX / HTML）→ Spec 102
- Chat history persistence → Spec 103
- Quality eval → Spec 104
- UI 改動 → Spec 105
- 改 `Settings` 預設值（如 `chunk_size`、`top_k`）
- 加新依賴（除標準庫外，本 spec 不加任何 pip 套件）

---

## 3. 核心設計決策

### 3.1 11 個 module 拆檔（單職責原則）

**決定**：依「資料 → 索引 → 檢索 → 生成」順序拆 11 個 `.py`，每檔只負責一個明確職責；`rag.py` 改成 façade。

| 模組 | 職責 | 對應 Tier 1 程式段 |
|---|---|---|
| `src/config.py` | `Settings`（pydantic_settings） | `rag.py` L47-69 |
| `src/logging_setup.py` | `logging.basicConfig` + noisy 壓 WARNING | `rag.py` L23-35 |
| `src/loaders/__init__.py` | `load_file()` dispatcher（按副檔名分流） | `rag.py` L75-90 |
| `src/loaders/text_loader.py` | `.md` / `.txt` 內部實作 | 同上 |
| `src/loaders/pdf_loader.py` | `.pdf` 內部實作 | 同上 |
| `src/chunking.py` | `chunk_documents()` + `_splitter` | `rag.py` L96-121 |
| `src/vectorstore.py` | `get_vectorstore()` / `list_sources()` / `fetch_chunks_by_ids()` | `rag.py` L127-169 |
| `src/ingest.py` | `ingest_paths()` | `rag.py` L175-195 |
| `src/retrieval.py` | `RetrievedChunk`（Pydantic）+ `retrieve()` | `rag.py` L201-233 |
| `src/prompts.py` | `SYSTEM_PROMPT` / `_USER_TEMPLATE` / `_BLOCK_TEMPLATE` 常數 | `rag.py` L239-257 |
| `src/citation.py` | `renumber_and_filter()`（public，原為 `_renumber_and_filter`） | `rag.py` L278-321 |
| `src/llm.py` | `_get_llm()`（內部，但暴露 helper 給 `rag_chain`） | `rag.py` L269-275 |
| `src/rag_chain.py` | `query()` + `RagAnswer`（Pydantic）+ `CitedChunkRef` | `rag.py` L324-358, L262-266 |

**為何**：
- 三 Phase 2 teammate 在三條不同路徑（`src/loaders/*`、`src/history/*`、`src/eval/*`）+ UI 在 `app.py`，可完全平行
- 每檔 < 100 行，testability 提升
- `prompts.py` 獨立化讓未來版本化 prompt（Phase 4+ backlog）零阻力

**影響**：`app.py` 內 `from rag import ...` 不變，但 `rag.py` 內部從直接定義 → re-export from `src.*`。

### 3.2 `RetrievedChunk` / `RagAnswer` 改 Pydantic v2

**決定**：保留欄位名與順序，從 `@dataclass` 改成 `pydantic.BaseModel`，並加 `model_config = ConfigDict(extra="forbid")`。

```python
class RetrievedChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")
    n: int = Field(..., ge=1)
    chunk_id: str
    text: str
    source: str
    page: int = Field(default=0, ge=0)
    chunk_index: int = Field(..., ge=0)
    score: float
```

**為何**：
- Tier 1 `replace(chunk_by_old_n[old], n=new)` 用 `dataclasses.replace`；Pydantic 等價為 `chunk.model_copy(update={"n": new})`（**citation.py 的 renumber 實作要改這一行**）
- Spec 103 落地 SQLite 前要 `model_dump()` 序列化；dataclass `asdict()` 不支援 strict mode
- `extra="forbid"` 確保未來欄位飄移時 model_validate 立刻爆，不靜默忽略

**影響**：
- `citation.py` 內 `replace(...)` → `model_copy(update=...)`
- `app.py` 對 `RetrievedChunk` 屬性的讀取（`c.n`、`c.chunk_id` 等）不需改
- Pydantic v2 與 dataclass 的 `==` 行為差異：BaseModel 預設 deep compare 欄位，與 dataclass 行為一致，已驗證

### 3.3 `rag.py` 改成 10 行內 façade

**決定**：`rag.py` 整檔縮成純 re-export，**內容只有 imports + `__all__`**，不留任何邏輯：

```python
"""Backward-compat façade. New code: import from `src.*` directly."""
from src.ingest import ingest_paths
from src.retrieval import RetrievedChunk, retrieve
from src.rag_chain import RagAnswer, query
from src.vectorstore import fetch_chunks_by_ids, list_sources

__all__ = [
    "ingest_paths", "RetrievedChunk", "retrieve",
    "RagAnswer", "query", "fetch_chunks_by_ids", "list_sources",
]
```

**為何**：
- AC #3 要求 `app.py` 一行不改仍可啟動 → `rag.py` 不能消失，只能變空殼
- Spec 105 在 Phase 3 才會改 `app.py` 用 `from src.* import ...`

**影響**：façade 是「過渡橋」，Spec 105 完成後可保留也可刪除（Spec 105 自行決定）。

### 3.4 `_renumber_and_filter` 改名為 `renumber_and_filter`（public）

**決定**：把舊底線前綴拿掉，正式 export；保留函式 signature 與所有實作行為。

**為何**：
- 拆檔後 `rag_chain.query()` 從另一個 module（`src/citation.py`）import 它，底線前綴會誤導讀者以為是 module-private
- Spec 104 的 quality eval 也會 import 它（用來重複測「重編號後句子內的 `[n]` markers 對 cited chunks 反查」）

**影響**：所有對 `_renumber_and_filter` 的呼叫改名；`tests/unit/test_citation.py` 也用新名稱。

### 3.5 Logging 行為完全保留

**決定**：`src/logging_setup.py` 在 import 時執行 `logging.basicConfig(...)` 與 noisy 壓 WARNING，**並由 `src/__init__.py` 在 package import 時自動呼叫一次**（與 Tier 1 import `rag` 時自動 init 行為一致）。

**為何**：
- Tier 1 `rag.py` 在 module top-level 設 logging；migration 後若不自動 init，CLI 跑 unit test 會出現 propagation 不一致
- Logger 名稱保留 `log = logging.getLogger("rag")`（不改名為 `src` 或 `rag_chain`），讓既有 INFO 字串完全相同（grep 友善）

**影響**：`src/__init__.py` 內 `from src.logging_setup import setup_logging; setup_logging()`，副作用一次性。

### 3.6 Tier 1 既有行為清單（不可破壞）

| 行為 | 規則 | 驗收方式 |
|------|------|----------|
| `chunk_id` 格式 | `f"{doc_id}:{chunk_index}"` + `doc_id = md5(source)[:10]` | AC #2 |
| Renumber 規則 | 依首次出現順序重編 1..N | AC #1 |
| 編造編號處理 | 從答案文字中刪除 marker（不只是過濾 citations list） | AC #1 |
| 雙空白壓縮 | renumber 收尾 `re.sub(r" {2,}", " ", ...)` | AC #1 |
| `fetch_chunks_by_ids` 部分命中 | 缺 id 不出現在 dict、不 raise | AC #4 |
| Empty retrieval | 回 `"依現有資料無法回答：知識庫目前是空的..."` 含完整字串 | AC #6 |
| Logging 名稱 | `logging.getLogger("rag")` 不改 | AC #7 |
| Prompt 字串 | `SYSTEM_PROMPT` / `_USER_TEMPLATE` / `_BLOCK_TEMPLATE` byte-identical | AC #8 |

---

## 4. 詳細規格

### 4.1 檔案地圖（Migration 後）

```
tag_rag/
├── app.py                    # 不動（AC #3）
├── rag.py                    # 10 行內 façade
├── pyproject.toml            # 不動（無新依賴）
├── src/
│   ├── __init__.py           # auto-call setup_logging()
│   ├── config.py             # Settings
│   ├── logging_setup.py      # setup_logging()
│   ├── loaders/
│   │   ├── __init__.py       # load_file() dispatcher
│   │   ├── text_loader.py    # .md / .txt
│   │   └── pdf_loader.py     # .pdf
│   ├── chunking.py           # chunk_documents()
│   ├── vectorstore.py        # get_vectorstore / list_sources / fetch_chunks_by_ids
│   ├── ingest.py             # ingest_paths()
│   ├── retrieval.py          # RetrievedChunk + retrieve()
│   ├── prompts.py            # SYSTEM_PROMPT / _USER_TEMPLATE / _BLOCK_TEMPLATE
│   ├── citation.py           # renumber_and_filter() (rename, public)
│   ├── llm.py                # _get_llm()
│   └── rag_chain.py          # query() + RagAnswer + CitedChunkRef
├── tests/
│   ├── unit/
│   │   ├── test_citation.py
│   │   └── test_chunking.py
│   ├── integration/
│   │   └── test_pipeline_end_to_end.py
│   └── fixtures/
│       └── docs/
│           ├── tiny.pdf      # 2 頁、< 5KB
│           ├── tiny.md       # 1 段
│           └── tiny.txt      # 1 段
└── scripts/
    └── regression.sh
```

### 4.2 介面（不可變動）

| 函式 / 類別 | Signature | 出處 module |
|---|---|---|
| `ingest_paths(paths: list[str]) -> int` | 不變 | `src/ingest.py` |
| `retrieve(question: str, k: int \| None = None) -> list[RetrievedChunk]` | 不變 | `src/retrieval.py` |
| `query(question: str) -> RagAnswer` | 不變 | `src/rag_chain.py` |
| `list_sources() -> list[str]` | 不變 | `src/vectorstore.py` |
| `fetch_chunks_by_ids(chunk_ids: list[str]) -> dict[str, dict]` | 不變 | `src/vectorstore.py` |
| `renumber_and_filter(answer: str, retrieved: list[RetrievedChunk]) -> tuple[str, list[RetrievedChunk]]` | **改名（去底線）** | `src/citation.py` |
| `load_file(path: str \| Path) -> list[Document]` | 不變 | `src/loaders/__init__.py` |
| `chunk_documents(docs: list[Document]) -> list[Document]` | 不變 | `src/chunking.py` |

### 4.3 `renumber_and_filter` 演算法（複製自 Tier 1，docstring 範例不變）

複製 `rag.py` L278-321 全部邏輯，**唯一差異**：
- 函式名去底線
- `from dataclasses import replace` → 改用 `RetrievedChunk.model_copy(update={"n": new})`

docstring 內範例必須保留：

```text
範例：
  retrieved n = [1,2,3,4,5]
  LLM 原答：'句A [2]. 句B [4][2][99].'
  seen_order = [2, 4]（99 不在範圍）
  remap = {2: 1, 4: 2}
  新答：'句A [1]. 句B [2][1].'
  citations = [chunk(原 n=2, 新 n=1), chunk(原 n=4, 新 n=2)]
```

### 4.4 Tiny fixtures

| 檔案 | 內容 | 大小上限 |
|---|---|---|
| `tests/fixtures/docs/tiny.md` | 至少 1 個 heading + 2 段、共 ≥ 100 字 | 1 KB |
| `tests/fixtures/docs/tiny.txt` | 1 段純文字 ≥ 100 字 | 1 KB |
| `tests/fixtures/docs/tiny.pdf` | 1-2 頁、< 5 KB、可被 PyPDFLoader 解析 | 5 KB |

### 4.5 5 條 baseline tests

| Test | 檔案 | 驗證 |
|---|---|---|
| `test_renumber_basic` | `tests/unit/test_citation.py` | docstring 範例字串輸入 → 輸出 `"句A [1]. 句B [2][1]."` + citations.n = [1,2] |
| `test_renumber_empty_when_no_marker` | `tests/unit/test_citation.py` | answer 不含任何 `[n]` → 回原字串 + `citations == []` |
| `test_chunk_id_stable_after_double_ingest` | `tests/unit/test_chunking.py` | 同檔 chunk 兩次，所有 `chunk_id` byte-identical |
| `test_fetch_chunks_partial_hit` | `tests/integration/test_pipeline_end_to_end.py` | 5 ids 中 3 個存在 → 回 dict 只有 3 個 key、不 raise |
| `test_query_smoke` | `tests/integration/test_pipeline_end_to_end.py` | ingest tiny.md → query → `RagAnswer` 是有效 Pydantic 實例（mock LLM 回 fixed 字串） |

> 第 5 條 `test_query_smoke` 用 monkeypatch 替換 `src.llm._get_llm`，LLM 不打真 Ollama。

### 4.6 `scripts/regression.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
pytest tests/unit -q
pytest tests/integration -q -m "not requires_ollama"
# 若 Ollama 啟動再跑：
# pytest tests/integration -q -m requires_ollama
```

---

## 5. 特別處理

### 5.1 `app.py` 不可改一行

AC #3 的「一行不改」是強約束。實作 façade 時必須驗證：
- `from rag import RetrievedChunk, fetch_chunks_by_ids, ingest_paths, list_sources, query` 仍可成功
- `c.n` / `c.chunk_id` / `c.text` / `c.source` / `c.page` / `c.chunk_index` / `c.score` 屬性存取仍正常（Pydantic v2 BaseModel 支援屬性存取）
- `RetrievedChunk` 仍可作為 `dict[str, RetrievedChunk]` 的 value（model 是 hashable=False 但 dict value 不需 hash，OK）

### 5.2 logging 設定的副作用順序

`src/__init__.py` 必須在 **第一次 from src import** 時就執行 `setup_logging()`，且只執行一次（用 module-level guard）。否則 unit test parallel run 時會重複 basicConfig 而產生重複 handler。

```python
# src/__init__.py
from src.logging_setup import setup_logging
setup_logging()  # idempotent
```

### 5.3 Pydantic v2 `model_copy` 與 dataclass `replace` 的等價性

```python
# Tier 1 (rag.py L313-316)
new_citations = [
    replace(chunk_by_old_n[old], n=new)
    for old, new in sorted(remap.items(), key=lambda x: x[1])
]

# Migration 後 (src/citation.py)
new_citations = [
    chunk_by_old_n[old].model_copy(update={"n": new})
    for old, new in sorted(remap.items(), key=lambda x: x[1])
]
```

`model_copy(update=...)` 預設淺拷貝，欄位語意與 `replace(...)` 完全一致。

### 5.4 Logger 名稱保留為 `"rag"`

每個 `src/*.py` 內仍用 `log = logging.getLogger("rag")`，**不**改成 `__name__`。理由：保留 Tier 1 grep 字串完全可比對（如 `[chunk_documents] 5 docs → 12 chunks` 等）。

---

## 6. DTO 欄位設計總表

### RetrievedChunk

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `n` | int (≥1) | Y | 顯示編號（renumber 後 1..N） |
| `chunk_id` | str | Y | `"{doc_id}:{chunk_index}"` |
| `text` | str | Y | chunk 內文快照 |
| `source` | str | Y | 來源檔名（XLSX 為 `"{filename}#{sheet_name}"`） |
| `page` | int (≥0) | N（default 0） | PDF 頁碼，非 PDF 為 0 |
| `chunk_index` | int (≥0) | Y | 該 doc_id 內 chunk 序號 |
| `score` | float | Y | cosine relevance |

### CitedChunkRef（供 Spec 103 消費）

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `chunk_id` | str | Y | 同 RetrievedChunk.chunk_id |
| `display_n` | int (≥1) | Y | UI 顯示用 `[n]` |

### RagAnswer

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `answer` | str | Y | 已 renumber + 壓雙空白 |
| `citations` | list[RetrievedChunk] | N（default []） | 被引用的 chunks，n=1..len |
| `retrieved` | list[RetrievedChunk] | N（default []） | retrieve 全部回傳，n=1..k |

---

## 7. 與外部系統的關係

- **Chroma DB**：`src/vectorstore.py` 仍用 `langchain_chroma.Chroma` + `PersistentClient`；persist dir 由 `Settings.chroma_dir` 控（不動預設值 `./data/chroma`）。
- **Ollama / OpenAI 相容 API**：`src/llm.py` 與 `src/vectorstore.py` 內 embedding 走 `langchain_openai.ChatOpenAI` + `OpenAIEmbeddings`，預設 base_url `http://localhost:11434/v1`（不動）。
- **無新外部依賴**：pyproject.toml 不加任何套件。

---

## 8. Acceptance Criteria

1. **Renumber 演算法保留**：執行 `pytest tests/unit/test_citation.py::test_renumber_basic` 全綠；該 test 內 input `("句A [2]. 句B [4][2][99].", [chunks n=1..5])` 必輸出 answer = `"句A [1]. 句B [2][1]."` 且 `[c.n for c in citations] == [1, 2]`。
2. **`chunk_id` 穩定且 ingest 冪等**：執行 `pytest tests/unit/test_chunking.py::test_chunk_id_stable_after_double_ingest` 全綠；用 `tiny.md` 連 ingest 2 次後 `get_vectorstore()._collection.count()` 與第一次 ingest 後相等，且所有 `chunk_id` byte-identical（直接 set-equal）。
3. **`app.py` 一行不改可啟動**：執行 `python -c "import app"` 不 raise；diff 比對 migration 前後 `app.py` 全檔，0 行差異。
4. **`fetch_chunks_by_ids` 部分命中**：執行 `pytest tests/integration/test_pipeline_end_to_end.py::test_fetch_chunks_partial_hit` 全綠；給 5 ids 中 3 個確實存在，回傳 dict `len == 3`、不 raise。
5. **三格式 loader 行為與 Tier 1 hash-equal**：`load_file("tests/fixtures/docs/tiny.md")` 對 `.pdf` / `.md` / `.txt` 三種，回傳的 `[d.page_content for d in docs]` 與 Tier 1 (`rag.py`) 對同檔回傳的 byte-identical（用 `hashlib.md5(json.dumps(...).encode()).hexdigest()` 比對）。
6. **Empty retrieval 字串完整**：清空 Chroma → `query("hello")` 回 `RagAnswer.answer` 必含字串 `"依現有資料無法回答：知識庫目前是空的"`，且 `citations == []`、`retrieved == []`。
7. **Logger 名稱仍為 `"rag"`**：執行 `import src.chunking; assert src.chunking.log.name == "rag"`（任一 src module 同樣行為）。
8. **Prompt 字串 byte-identical**：`src.prompts.SYSTEM_PROMPT == <Tier 1 字串>` 為 True；`_USER_TEMPLATE`、`_BLOCK_TEMPLATE` 同樣 assert byte-identical（用本 spec author 提供的 snapshot 字串）。
9. **DTO schema 鎖死**：執行 `RetrievedChunk.model_validate(json.load(open("specs/100-*/contracts/fixtures/retrieved_chunk_example.json")))` 與同 fixture 對 `RagAnswer`，均不 raise。
10. **`rag.py` 是 façade**：`wc -l rag.py` ≤ 12（含空行與 docstring）；`import ast; ast.parse(open("rag.py").read())` 後 top-level 只有 ImportFrom + Assign（`__all__`），無 FunctionDef / ClassDef。
11. **`scripts/regression.sh` 全綠**：`bash scripts/regression.sh` 退出碼 0（不包含 `requires_ollama` 標記）。

---

## 9. 與其他 spec 的介面

| 對象 spec | 本 spec 暴露 / 消費什麼 | 對方怎麼用 |
|---|---|---|
| **Spec 102 Multi-format Loaders** | **暴露** `src/loaders/__init__.py` dispatcher、`Document` metadata 慣例（`source` / `page` / `doc_id` / `chunk_index`） | Spec 102 在 dispatcher 內加 `.docx` / `.xlsx` / `.html` 分支；不可改 `.md` / `.txt` / `.pdf` 既有行為 |
| **Spec 103 Chat History** | **暴露** `RetrievedChunk` + `CitedChunkRef`（chunk_id + display_n） | Spec 103 的 `StoredCitation` schema 內 `chunk_id` / `display_n` 欄位必須與本 spec 同名同型 |
| **Spec 104 Quality Eval** | **暴露** `RetrievedChunk`、`RagAnswer`、`renumber_and_filter` | Spec 104 的 `evaluate(answer, retrieved)` 直接吃 `RagAnswer.answer` + `RagAnswer.retrieved` 兩欄位 |
| **Spec 105 UI Integration** | **暴露** 公開 API 改由 `src.*` 直接 import；本 spec 留下的 `rag.py` façade Spec 105 可選擇是否刪除 | UI 改 `from src.ingest import ingest_paths` 等；Spec 105 自行決定 façade 去留 |

---

## 10. Out of scope（再次強調）

- **任何新功能**（**第 2 次重複提醒**）
- **改 chunk_id 演算法**（**第 2 次重複提醒**）：`f"{doc_id}:{chunk_index}"` 與 `doc_id = md5(source)[:10]` 是 Tier 1 已驗證契約
- **改 renumber 演算法**（**第 2 次重複提醒**）：包含首次出現順序、編造編號刪除、雙空白壓縮
- **改 prompt 字串**（**第 2 次重複提醒**）：`SYSTEM_PROMPT` / `_USER_TEMPLATE` / `_BLOCK_TEMPLATE` 一字不改
- **加新依賴**：本 spec 純拆檔，無新 pip 套件
- DOCX / XLSX / HTML loader → Spec 102
- SQLite history → Spec 103
- Quality / hallucination eval → Spec 104
- UI sidebar / quality panel → Spec 105
- 改 `Settings` 預設值
- 改 logger handler / formatter（保留 Tier 1 字串格式）
- 改 `Settings.chunk_size` / `chunk_overlap` / `top_k` 預設
- 把 `_get_llm()` 暴露為 public（仍是 `_` 前綴，內部用）

---

## 11. 參考

- 重建計畫：`~/.claude/plans/rag-citation-mvp-rag-citation-memoized-locket.md` §「Spec 100 — Migration & Foundation」、§「Phase 1 — Migration」
- 既有 Tier 1 程式碼：`rag.py`（350 行）、`app.py`（100 行）
- SDD 規範：[`specs/CLAUDE.md`](../CLAUDE.md)
- Profile：`~/.claude/skills/sdd-agent-teams/references/profiles/python-llm.md`
- 下游 spec：[Spec 102](../102-multi-format-loaders/spec.md)、[Spec 103](../103-chat-history-persistence/spec.md)、[Spec 104](../104-quality-eval-hallucination/spec.md)、[Spec 105](../105-ui-integration/spec.md)
