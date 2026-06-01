# Spec 105 — UI Integration

> 對應重建計畫 §「Spec 105 — UI Integration」、§「Phase 3 — Integration & Polish」、§「End-to-End UAT」。
> 上游：Spec 100 / 102 / 103 / 104（全部）。
> 下游：無（最終整合 spec）。

---

## 1. Context

Tier 1 的 `app.py`（100 行）只做：上傳 → ingest → query → 顯示答案 + citation expander。Phase 1-2 完工後上游能力（多格式 loader、SQLite history、quality eval）已 ready，但 `app.py` 仍是 Tier 1 版本。痛點：

1. **新格式上傳通道未開**：`st.file_uploader(type=["pdf", "md", "txt"])` 沒包含 docx / xlsx / html，使用者點上傳看不到新副檔名。
2. **對話只活在 session**：Spec 103 的 `HistoryStore` 已寫好但無 UI 入口；切 sidebar、選對話、刪對話的視覺缺失。
3. **Hallucination 不可見**：Spec 104 的 `evaluate()` 雖能算 `quality_score`，但 UI 沒顯示，使用者照樣看不到風險指示。
4. **import 仍走 `rag.py` façade**：Phase 1 留下的橋接層使命達成；繼續用會讓「`src.*` 是 canonical 來源」這個敘事不一致。

本 spec 把 `app.py` 改寫成「靠 `src.*` 直接 import + sidebar + quality panel + 4 格式上傳」，並更新 README / CLAUDE.md / pyproject.toml。**不**做 UI 美化、**不**做自訂 prompt、**不**做匯出對話。

---

## 2. Scope

### In scope

- 改 `app.py`：
  - import 全部改為 `from src.* import ...`（拿掉 `from rag import ...`）
  - `st.file_uploader(type=[...])` 用 `SUPPORTED_EXTS`
  - 加左側 sidebar：對話列表、新增按鈕、選擇 / 刪除 / 重命名
  - citation expander 下方加 QualityReport 區塊
- 改 `pyproject.toml`：鎖定 Spec 102 新依賴版本
- 改 `.env.example`：加 `HISTORY_DB_PATH` 範例（與 Spec 103 `Settings.history_db_path` 對齊）
- 改 `README.md`：列出 4 種新 ext + history + eval 章節
- 改 `CLAUDE.md`（root）：更新「目前 Phase 狀態」段
- 改 `specs/plan.md` 的 status 欄（標 ✅ Done）
- 是否刪除 `rag.py` façade：由 ui-integrator 決定（保留也可，不影響功能）

### Out of scope

- **UI 美化**（**第 1 次重複提醒**）：用 Streamlit 內建 component，不自寫 CSS / HTML
- **自訂 prompt**（**第 1 次重複提醒**）：使用者不可從 UI 改 SYSTEM_PROMPT
- **匯出對話為 markdown / pdf**（**第 1 次重複提醒**）：v3 backlog
- 修改任何上游 module（`src/*` 一行不動，本 spec 純整合）
- 改 `Settings` 預設值（如 `chunk_size`、`top_k`）
- 加 streaming 答案
- 多使用者切換 UI
- 對話搜尋
- 上傳時的格式自動偵測 fallback（依賴 dispatcher 報錯）
- 加 auth 登入
- WebSocket / SSE
- 改 logging 格式
- 加 dev tool / debug panel

---

## 3. 核心設計決策

### 3.1 三個分區的 UI 結構

**決定**：

```
┌──────────────────────────────────────────────────┐
│ Sidebar (左)                                     │
│  - + 新增對話                                    │
│  - 對話列表（依 created_at DESC）                │
│    [選中] 信用卡業務問答 · 5/26  [✕]            │
│            銀行法規條文比對 · 5/25  [✕]         │
│            ...                                   │
├──────────────────────────────────────────────────┤
│ Main (右)                                        │
│  Tab 1: 📥 文件管理（沿用 Tier 1，擴 type list）│
│  Tab 2: 💬 問答（沿用 Tier 1，加 QualityReport）│
└──────────────────────────────────────────────────┘
```

**為何**：
- Streamlit 原生 `st.sidebar` + `st.tabs`，不需自寫 layout
- 沿用 Tier 1 已 demo 的 2-tab 結構，使用者學習成本最小
- Sidebar 與 main 分離讓「切對話」操作不影響 tab 狀態

**影響**：`st.session_state` 需新增 keys：`current_conv_id`、`history_store`（cache 為 resource 取得單例）。

### 3.2 `HistoryStore` 為 Streamlit `cache_resource` 單例

**決定**：

```python
@st.cache_resource
def _get_history_store() -> HistoryStore:
    return HistoryStore(settings.history_db_path)
```

**為何**：
- `HistoryStore` 內每方法自己 manage connection（spec 103 §3.3），不存長連線
- `cache_resource` 在 Streamlit reload 時 dedupe，避免重複 init schema
- 與 Spec 103 §5.1「連線 per-call」設計相容（store 是無狀態 facade）

**影響**：實際 SQLite connection 每方法新建，與 Streamlit thread model 相容。

### 3.3 切對話的 state 流程

**決定**：

1. 啟動時 `st.session_state.current_conv_id` 為 None
2. Sidebar 顯示 `list_conversations()`；點某個 conv → `current_conv_id = conv.id`、清空 `messages`、`load_conversation(conv_id)` 灌回 `messages`
3. 點「新增對話」→ `create_conversation(title="")` → 新 conv.id → 清空 messages
4. 使用者送出第一則 user message 時：若 `title == ""` → 自動 rename 為訊息前 30 字
5. 點刪除（垃圾桶 icon）→ confirm 後 `delete_conversation`；若刪到 current → current_conv_id 清空、UI 顯示「請選擇或新增對話」

**為何**：
- 與 ChatGPT 行為一致
- 第一訊息自動 rename 比強制使用者預先打標題友善

**影響**：`render_chat` 在 `current_conv_id is None` 時顯示空狀態，避免 user 在無對話下送訊息。

### 3.4 QualityReport 區塊位置

**決定**：放在 citation expander **下方**（同層級、依序顯示）。

```python
# 偽程式
with st.chat_message("assistant"):
    st.markdown(ans.answer)
    render_citations(ans.citations)
    if ans.retrieved:  # 有檢索結果才評估
        report = evaluate(ans.answer, ans.retrieved)
        render_quality_report(report)
```

**為何**：
- citation 是「答案來源」、quality 是「答案信心」→ 語義上 citation 先、quality 後
- 兩者都是 expander，避免淹沒答案本身
- 「依現有資料無法回答」（retrieved 為空）情況下不顯示 quality report（避免顯示 quality_score=0.0 的誤導）

**影響**：UI 順序固定：answer → citations → quality_report；不可顛倒。

### 3.5 QualityReport 視覺呈現

**決定**：

```
┌─ 🔍 品質檢查 · score: 0.80 ─────────────────────┐
│  逐句 support：                                 │
│   ✓ 台新銀行...300 萬張 [1]                     │
│   ✓ 同年數位帳戶突破 200 萬 [2]                 │
│   ✗ 同年營收達 100 億元 [1] · overlap=0.05      │
│   ✓ 法金業務聚焦中小企業 [3]                    │
│  ⚠️ 未支持實體（regex 偵測）：                  │
│   🔴 100 億 (num): not found in any cited chunk │
└──────────────────────────────────────────────────┘
```

- `quality_score` 顯示為 2 位小數 + 顏色（≥0.8 綠 / ≥0.5 黃 / < 0.5 紅）
- 逐句 support 用 ✓ / ✗ icon
- unsupported entities 用紅色 `:red[...]` markdown

**為何**：
- 一眼可看品質訊號
- 詳細列表給使用者「為何被標」的可解釋性

**影響**：用 Streamlit `st.markdown` + emoji + `:red[...]` markup；不寫 CSS。

### 3.6 stale 反查邏輯保留

**決定**：渲染 `Message.citations` 時，邏輯與 Tier 1 `app.py` `render_citations` 一致：

```python
live = fetch_chunks_by_ids([c.chunk_id for c in citations])
for c in citations:
    entry = live.get(c.chunk_id, {})
    md = entry.get("metadata") or {}
    text = entry.get("text") or c.snapshot_text  # ← StoredCitation 改用 snapshot_text
    stale = c.chunk_id not in live
```

**為何**：與 Tier 1 設計理念一致；Spec 103 已把 snapshot 持久化進 SQLite，但 UI 優先用 Chroma 最新內容。

**影響**：`render_citations` 需同時支援 `RetrievedChunk`（新對話的回答）與 `StoredCitation`（從 DB 載入的舊對話）。實作上用兩個 helper 或一個 polymorphic helper 都可（ui-integrator 自決）。

### 3.7 import 改為 `src.*`

**決定**：

```python
# Tier 1
from rag import RetrievedChunk, fetch_chunks_by_ids, ingest_paths, list_sources, query

# Spec 105 後
from src.config import settings
from src.eval.report import evaluate
from src.history.store import HistoryStore
from src.history.models import Message, MessageRole, StoredCitation
from src.ingest import ingest_paths
from src.loaders import SUPPORTED_EXTS
from src.rag_chain import query
from src.retrieval import RetrievedChunk
from src.vectorstore import fetch_chunks_by_ids, list_sources
```

**為何**：
- Phase 1 façade 過渡使命完成
- canonical import path 確立後續開發者預期

**影響**：`rag.py` 可保留也可刪除；保留無害（不引入新依賴）。

---

## 4. 詳細規格

### 4.1 `app.py` 模組結構

```
app.py
├── header / page_config
├── _get_history_store() (@st.cache_resource)
├── _init_session_state()
├── render_sidebar()
│   ├── + 新增對話
│   ├── 對話列表（每筆 button + 刪除 icon）
├── render_doc_tab()
│   ├── file_uploader(type=SUPPORTED_EXTS)
│   ├── ingest 按鈕
│   ├── list_sources() 顯示
├── render_chat_tab()
│   ├── if current_conv_id is None: 空狀態
│   ├── for msg in messages: render_message(msg)
│   ├── chat_input
├── render_message(msg) ← user 與 assistant 共用
├── render_citations(citations) ← polymorphic（RetrievedChunk / StoredCitation）
├── render_quality_report(report)
```

### 4.2 `st.session_state` keys

| Key | 型別 | 預設 | 說明 |
|---|---|---|---|
| `current_conv_id` | str \| None | None | 當前選中對話的 UUID4 |
| `messages` | list[dict] | [] | UI 顯示用的 messages cache；每次切對話重灌 |
| `pending_rename` | bool | False | 標記下次 user 送訊息時自動 rename |

> `messages` 內 dict 結構：`{"role": str, "content": str, "citations": list[RetrievedChunk | StoredCitation]}`。

### 4.3 query → 持久化流程

```python
if q := st.chat_input("..."):
    # 1. 確保有 conv
    if st.session_state.current_conv_id is None:
        conv = store.create_conversation(title="")
        st.session_state.current_conv_id = conv.id
        st.session_state.pending_rename = True

    # 2. 加 user message
    store.add_message(conv_id, MessageRole.USER, q)
    st.session_state.messages.append({"role": "user", "content": q, "citations": []})

    # 3. 跑 query
    ans = query(q)

    # 4. 持久化 assistant message + citations
    stored_citations = [
        StoredCitation(
            chunk_id=c.chunk_id, display_n=c.n, score=c.score,
            snapshot_text=c.text[:1000],
        ) for c in ans.citations
    ]
    store.add_message(conv_id, MessageRole.ASSISTANT, ans.answer, citations=stored_citations)
    st.session_state.messages.append({
        "role": "assistant", "content": ans.answer,
        "citations": ans.citations,  # in-memory 仍是 RetrievedChunk（即時 reuse）
    })

    # 5. 自動 rename
    if st.session_state.pending_rename:
        store.rename_conversation(conv_id, q[:30])
        st.session_state.pending_rename = False
```

### 4.4 切對話流程

```python
def switch_conversation(conv_id: str) -> None:
    conv, msgs = store.load_conversation(conv_id)
    st.session_state.current_conv_id = conv_id
    st.session_state.messages = [
        {"role": m.role.value, "content": m.content, "citations": m.citations}
        for m in msgs
    ]
```

### 4.5 pyproject.toml 變動

需鎖：

```toml
[project]
dependencies = [
    # ... Tier 1 既有 ...
    "python-docx>=1.1",
    "openpyxl>=3.1",
    "beautifulsoup4>=4.12",
    "lxml>=5.0",
]
```

### 4.6 .env.example

```bash
# Tier 1 既有
OLLAMA_BASE_URL=http://localhost:11434/v1
LLM_MODEL=gemma4:e4b
EMBED_MODEL=bge-m3:latest
CHROMA_DIR=./data/chroma
LOG_LEVEL=INFO

# Spec 103 新增
HISTORY_DB_PATH=./data/history.sqlite
```

### 4.7 README.md 章節

新增章節：

```
## Supported file formats
- .pdf, .md, .txt（Tier 1）
- .docx（Spec 102）
- .xlsx（Spec 102）
- .html / .htm（Spec 102）

## Chat history
持久化於 ./data/history.sqlite。可從 UI sidebar 切換 / 新增 / 刪除對話。

## Quality evaluation
每則答案下方顯示 quality_score（句級 supported 比例）與 unsupported entities。
純規則式、零 LLM 呼叫、< 500ms。
```

---

## 5. 特別處理

### 5.1 Streamlit rerun 不丟對話

Streamlit 每次 widget 互動都會 rerun 整支 `app.py`。靠以下保 state：
- `current_conv_id` 在 `session_state`，rerun 後仍在
- `messages` cache 也在 session_state；只在切對話時重灌
- `HistoryStore` 用 `cache_resource` 不被 rerun 銷毀

### 5.2 並發 ingest + 對話

使用者在「文件管理」tab 上傳大檔（ingest 慢）時，「問答」tab 仍可問舊對話。Spec 103 §3.3 WAL 已保證 store CRUD 不被 ingest 阻塞；本 spec 不在 ingest spinner 內阻擋對話 tab（Streamlit 本身就是同 thread 序列化執行，但這不影響 SQLite 並發測試的成立）。

### 5.3 確認刪除對話

刪除是 destructive 操作。使用 `st.popover` 或 `st.confirm`（如有）做二次確認，避免誤觸。實作層級可由 ui-integrator 決定（spec 不強制）。

### 5.4 空狀態 UX

- 無任何對話 → main 區顯示「請從左側新增對話開始」
- 有對話但未選 → 同上
- 有對話且選中但無訊息 → 顯示 chat_input + 空訊息列

### 5.5 fetch_chunks_by_ids batch

`render_citations` 對 message 內所有 citations 做**一次** `fetch_chunks_by_ids(ids)`，不逐個。Tier 1 已是這樣，本 spec 沿用。

### 5.6 page_config 一次性

`st.set_page_config(...)` 必須在 module top level 唯一一處；session_state init 在其後。

### 5.7 不刪除 `rag.py`

由 ui-integrator 自決。若刪除，需確認沒有第三方 script 還 `from rag import ...`。Tier 1 已知無此情形，保留也可。

---

## 6. 無新 DTO

本 spec **不**新增任何 Pydantic schema 或 fixture；純消費上游。所有 import 來源見 §4.3 與 §3.7。

---

## 7. 與外部系統的關係

- **Streamlit**：用 1.30+（既有依賴，不升級）
- **Chroma / Ollama**：透過 `src.*` 間接互動，無直接呼叫
- **SQLite**：透過 `HistoryStore` 間接

---

## 8. Acceptance Criteria

1. **從零啟動 4 格式 + 切對話 e2e**：
   1. 清空 `./data/` 後 `streamlit run app.py`
   2. 上傳 1× PDF + 1× DOCX + 1× XLSX + 1× HTML
   3. 「文件管理」tab 顯示 4 個（XLSX 因 `#sheet` 顯示為 N 個 source 行）
   4. 問跨檔問題 → 答案有 citation expander + QualityReport
   5. 點「+ 新增對話」→ 問另一題
   6. 切回對話 1 → 內容（含 citations + assistant message）完整顯示

2. **QualityReport 視覺**：
   - 顯示 `quality_score` 數值 + 顏色（≥0.8 綠 / ≥0.5 黃 / < 0.5 紅）
   - 顯示逐句 ✓ / ✗
   - 至少一個 EntityFlag 時顯示紅色實體標籤
   - `retrieved == []`（空知識庫）時不顯示 QualityReport

3. **Streamlit rerun 不丟對話**：在已有對話的情況下，更改 `st.checkbox` / `st.text_input` 等任意 widget（觸發 rerun），對話列表 + 當前訊息全部保留。

4. **README.md 列出 4 種新副檔名**：用 `grep -E '\.docx|\.xlsx|\.html' README.md` 命中 ≥ 3 次。

5. **pyproject.toml 鎖定新依賴**：用 `grep -E 'python-docx|openpyxl|beautifulsoup4|lxml' pyproject.toml` 命中 4 次，且每行含 `>=` 版號。

6. **import 全部走 `src.*`**：`grep "from rag import" app.py` 命中 0 次；`grep "from src\\." app.py` 命中 ≥ 5 次。

7. **`.env.example` 含 `HISTORY_DB_PATH`**：`grep HISTORY_DB_PATH .env.example` 命中 1 次。

8. **`SUPPORTED_EXTS` 連結 file_uploader**：`app.py` 內 `st.file_uploader` 的 `type` 參數來源是 `from src.loaders import SUPPORTED_EXTS`（不可 hard-code list）。

9. **刪對話清空 current**：選 conv A 為 current → 刪 conv A → `current_conv_id` 為 None、main 區顯示空狀態。

10. **自動 rename**：新對話 title 初始為 `""`；送第一則 user message 後，`list_conversations()[0].title` 應為訊息前 30 字以內（非空）。

11. **citation snapshot 從 DB 載回**：建立對話 → 送 1 問 1 答（含 citations）→ 重啟 process → 切回該對話 → assistant 訊息的 `citations` 至少 1 筆且 `c.chunk_id` 與當時 query 結果相符；UI render 不 crash（即使 Chroma 該 chunk 已被刪也 fallback snapshot）。

12. **specs/plan.md status 全綠**：plan.md 內 100 / 102 / 103 / 104 / 105 五個 spec 狀態欄改為「✅ Done」。

---

## 9. 與其他 spec 的介面

| 對象 spec | 本 spec 暴露 / 消費什麼 | 對方怎麼用 |
|---|---|---|
| **Spec 100 Migration** | **消費** `src.config.settings`、`src.ingest.ingest_paths`、`src.rag_chain.query`、`src.retrieval.RetrievedChunk`、`src.vectorstore.fetch_chunks_by_ids` / `list_sources` | Spec 100 一行不動 |
| **Spec 102 Loaders** | **消費** `src.loaders.SUPPORTED_EXTS`、間接消費 docx/xlsx/html 三 loader | Spec 102 一行不動 |
| **Spec 103 History** | **消費** `src.history.store.HistoryStore` 全部 7 個方法、`src.history.models.{Conversation, Message, MessageRole, StoredCitation}` | Spec 103 一行不動 |
| **Spec 104 Eval** | **消費** `src.eval.report.evaluate` + `QualityReport` / `SentenceSupport` / `EntityFlag` schema | Spec 104 一行不動 |

---

## 10. Out of scope（再次強調）

- **UI 美化 / 自寫 CSS / HTML**（**第 2 次重複提醒**）
- **自訂 prompt UI**（**第 2 次重複提醒**）：使用者不可從 UI 改 SYSTEM_PROMPT
- **匯出對話**（**第 2 次重複提醒**）：v3 backlog
- 改任何上游 `src/*` module
- 改 Settings 預設值
- 串流答案 / WebSocket / SSE
- 多使用者切換
- 對話搜尋
- 上傳格式自動偵測 fallback
- auth 登入
- 改 logging 格式
- dev / debug panel
- 把 QualityReport 持久化到 SQLite（v3 backlog）

---

## 11. 參考

- 重建計畫：`~/.claude/plans/rag-citation-mvp-rag-citation-memoized-locket.md` §「Spec 105 — UI Integration」、§「End-to-End UAT」
- 上游：[Spec 100](../100-migration-foundation/spec.md)、[Spec 102](../102-multi-format-loaders/spec.md)、[Spec 103](../103-chat-history-persistence/spec.md)、[Spec 104](../104-quality-eval-hallucination/spec.md)
- SDD 規範：[`specs/CLAUDE.md`](../CLAUDE.md)
- Tier 1 UI 既有檔：`app.py`（沿用結構）
