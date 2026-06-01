# Spec 103 — Chat History Persistence

> 對應重建計畫 §「Spec 103 — Chat History Persistence」、§「Phase 2 — 功能並行」。
> 上游：Spec 100（`RetrievedChunk` / `CitedChunkRef` / `fetch_chunks_by_ids`）、Spec 102（不變動 `RetrievedChunk.source` 格式）。
> 下游：Spec 105（UI sidebar 對話列表、切換、新增、刪除）。

---

## 1. Context

Tier 1 的 chat state 只活在 `st.session_state.messages`（`app.py` L80-100）。痛點：

1. **重啟即丟**：Streamlit reload 或 process 重啟 → 全部對話消失。內部 demo 使用者反覆問同一份文件、想回看上週的問答，無法做到。
2. **無多對話切換**：所有訊息塞單一 `messages` list，沒法「開新主題對話、保留舊對話」。使用者只能新分頁開新 session（記憶體又分離）。
3. **Citation 持久化策略未定**：若直接序列化 `RetrievedChunk` 整包到 storage，未來 chunks 被刪/重切時資料會 stale 但 UI 不知道；Tier 1 已有的「`chunk_id` 反查最新原文 + stale 標籤」設計（`app.py` L20-39）需要保留到持久層。

本 spec 用 stdlib `sqlite3`（無新依賴）建立 `data/history.sqlite`，提供 `HistoryStore` CRUD 介面。Citation 持久化沿用 Tier 1 設計：只存 `chunk_id` + `display_n` + `score` + snapshot；渲染時用 `fetch_chunks_by_ids` 反查。**不**做多使用者、auth、雲端同步。

---

## 2. Scope

### In scope

- `src/history/store.py`：`HistoryStore` 類別，CRUD 介面 + WAL 設定
- `src/history/models.py`：re-export `Conversation` / `Message` / `StoredCitation` / `MessageRole` from contracts
- `src/history/__init__.py`：package init
- SQLite schema（兩張表 + FK CASCADE + WAL mode）
- `Settings.history_db_path` 新增欄位（預設 `"./data/history.sqlite"`）
- `tests/unit/test_history_store.py`：覆蓋 CRUD 與並發
- Pydantic schema + 3 fixtures

### Out of scope

- **多使用者 / auth / RBAC / 權限隔離**（**第 1 次重複提醒**）：DB 內無 user_id 欄位
- **雲端同步 / 多 device**（**第 1 次重複提醒**）：純 local SQLite
- **全文搜尋 conversation 內容**（**第 1 次重複提醒**）：UI 用標題 + 時間排序即可
- 對話匯出（markdown / pdf / json）→ v3 backlog
- 對話 fork / branch
- 自動 conversation 標題生成（用 first user msg 截前 N 字即可，由 store 端做）
- DB migration framework（schema 改動由 Spec author 用 `CREATE TABLE IF NOT EXISTS` 處理）
- 加密 SQLite（內部 demo 不需）
- 跨 process file locking 完美隔離（WAL 已足夠，不要 server）
- 任何對 Tier 1 retrieval / answer 流程的影響

---

## 3. 核心設計決策

### 3.1 SQLite stdlib，不用 ORM

**決定**：用 Python 標準庫 `sqlite3` + raw SQL。**不**引入 SQLAlchemy / sqlmodel / peewee 等 ORM。

**為何**：
- 內部 demo、單檔 DB、CRUD 不超過 6 個函式：ORM 純粹成本
- stdlib 零新依賴，符合 spec §2「無新依賴」
- raw SQL 對 reviewer 友善：schema 看得到、index 看得到、無 lazy load 陷阱

**影響**：
- `HistoryStore` 內每方法自己 manage cursor（`with sqlite3.connect(...) as conn:`）
- in-memory ↔ DB row 用 Pydantic model `model_dump()` / `model_validate()` 轉換
- Citation list 在 messages 表用 `citations_json TEXT` 欄存 JSON 字串

### 3.2 兩表 schema + FK CASCADE

**決定**：

```sql
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL  -- ISO8601 UTC
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conv_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    citations_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_conv_id ON messages(conv_id);
```

**為何**：
- `conversations.id` 用 TEXT（uuid4 字串）→ 跨 process 建立不撞號
- `messages.id` 用 INTEGER AUTOINCREMENT → 序號排序快、占空間小
- FK ON DELETE CASCADE：AC #3 直接砍 conversation 級聯刪所有 messages，不用兩階段 delete
- `idx_messages_conv_id`：list_messages by conv_id 是熱路徑
- 時間戳用 ISO8601 字串：可讀、可排序、不會踩 SQLite timezone 雷

**影響**：每次 connect 必須 `PRAGMA foreign_keys = ON`（SQLite 預設 OFF，這是常見陷阱）。

### 3.3 WAL mode + connection per-call

**決定**：
- 第一次連線後執行 `PRAGMA journal_mode=WAL`
- 每個 `HistoryStore` 方法內部 `with sqlite3.connect(self.db_path) as conn:` 開短連線，方法結束自動 commit + close
- **不**保留長連線 cached 在 instance

**為何**：
- Streamlit 用多 thread；長連線跨 thread 會 `Programming Error: SQLite objects created in a thread can only be used in that same thread`
- WAL 支援多讀者 + 單寫者並發（AC #5 並發測試需要）
- Connection per-call 是 SQLite 慣用 pattern，loader / ingest 同時跑也不阻塞

**影響**：性能上每次方法多 ~1ms connect 開銷，內部 demo 可接受。

### 3.4 Citation snapshot 上限 1000 字元

**決定**：`StoredCitation.snapshot_text` 上限 1000 字元；超過時 store 端 truncate 並加 `"…"`。schema 用 `max_length=1000` 強制驗證。

**為何**：
- Tier 1 chunk_size = 512 字元，常見 chunk 在 500 字內
- 1000 字元 buffer 留給未來 chunk_size 調大（< 4 倍）
- 用 schema validation 強制：避免 store 內忘了 truncate 而存進大 chunk

**影響**：
- 寫入時：`HistoryStore.add_message` 收到任意長 snapshot → 自動截斷 + `"…"`，再 Pydantic validate
- 讀取時：snapshot 已 ≤ 1000 字元，model_validate 必過

### 3.5 Citation 反查仍走 `fetch_chunks_by_ids`

**決定**：UI 渲染 message 時，取 `Message.citations[*].chunk_id` 集合 → 呼叫 `fetch_chunks_by_ids` → 命中用最新原文 + metadata；未命中 fallback 用 `StoredCitation.snapshot_text` + 顯示 stale 標籤。

**為何**：
- 與 Tier 1 設計理念一致（`app.py` L20-36）
- 文件被重新 ingest 或刪除時，UI 能正確顯示「文件已更新」
- 持久層只存最小資料，不會因 chunk 被改動而資料失同步

**影響**：
- Spec 103 store 層完全不知道 chunks 是否還在 Chroma；它只負責持久化
- Spec 105 UI 在 render 時做反查（與 Tier 1 `render_citations` 邏輯相同）

### 3.6 conversation title 自動生成規則

**決定**：`HistoryStore.create_conversation(title: str | None = None)`：
- 若 caller 傳 title → 用 title（最多 50 字元）
- 若 title 為 None → DB 內存空字串 `""`；UI 看到空標題顯示為「未命名對話」（UI 端規則）
- 提供 `rename_conversation(conv_id, new_title: str)` 用於後改名
- 提供 helper `_auto_title_from_message(content: str) -> str`：截取前 50 字元（store 內部可用，但 caller 自決是否呼叫）

**為何**：
- 與 ChatGPT 體驗一致：first user msg 截前 N 字當預設標題
- 給 caller 選擇權，不強耦合自動生成邏輯

---

## 4. 詳細規格

### 4.1 `HistoryStore` 介面

| 方法 | Signature | 行為 |
|---|---|---|
| `__init__` | `(self, db_path: str \| Path)` | 確保 parent dir 存在；首次 connect 時 `CREATE TABLE IF NOT EXISTS` + `PRAGMA journal_mode=WAL` |
| `create_conversation` | `(self, title: str \| None = None) -> Conversation` | 生 uuid4、塞 row、回填 `created_at` |
| `add_message` | `(self, conv_id: str, role: MessageRole \| str, content: str, citations: list[StoredCitation] \| None = None) -> Message` | 自動 truncate snapshot ≤ 1000；citations 序列化為 JSON；回 `Message` 含 DB 指派 id |
| `list_conversations` | `(self) -> list[Conversation]` | 依 `created_at DESC` 排序 |
| `load_conversation` | `(self, conv_id: str) -> tuple[Conversation, list[Message]]` | 同時回 conv 與 messages（依 messages.id ASC） |
| `delete_conversation` | `(self, conv_id: str) -> None` | FK CASCADE 自動刪 messages；conv_id 不存在不 raise（idempotent） |
| `rename_conversation` | `(self, conv_id: str, new_title: str) -> None` | UPDATE；不存在不 raise |

### 4.2 SQLite 設定（首次 connect 流程）

```python
def _init_db(self, conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS conversations (...);
        CREATE TABLE IF NOT EXISTS messages (...);
        CREATE INDEX IF NOT EXISTS idx_messages_conv_id ON messages(conv_id);
    """)
```

注意：`PRAGMA foreign_keys` 是 **per-connection** 設定，必須每次 connect 都重設。

### 4.3 Settings 擴充

`src/config.py` 內 `Settings` 加：

```python
history_db_path: str = "./data/history.sqlite"
```

### 4.4 Citation 序列化規則

```python
# add_message 內
citations_json = json.dumps(
    [c.model_dump() for c in (citations or [])],
    ensure_ascii=False,
)
```

`ensure_ascii=False` 保留中文可讀。

### 4.5 時間戳格式

`datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z"`，與 fixtures 對齊。讀回時用 `datetime.fromisoformat(...)`（Python 3.11+ 支援 trailing Z）；若不支援，先去 Z 再 parse。

### 4.6 conv_id 與 message.id 唯一性

- `conv_id`：uuid4 hex with hyphens（`uuid.uuid4()` 字串化）。collision 機率約 2^-122。
- `message.id`：DB AUTOINCREMENT，per-DB 單調遞增。

---

## 5. 特別處理

### 5.1 SQLite 在 Streamlit 多 thread 下的安全性

- 每方法 `sqlite3.connect(path)` 建新連線；不快取
- Streamlit `st.cache_resource` 不可用在 `HistoryStore`（會跨 thread 共用連線 → 炸）
- AC #5 並發測試模擬 thread 同時 ingest + add_message

### 5.2 `citations_json` 欄位 schema 飄移

未來 `StoredCitation` 加欄位時：
- Pydantic `extra="forbid"` 不允許 extra；舊資料 load 後 `model_validate` 會炸
- 解法（不在本 spec 實作，但設計上考慮）：reader 端 `model_validate` 失敗時 fallback `model_construct`，且 log warning。本 spec **不**實作此 fallback（前提：schema 不變）

### 5.3 路徑保險

`db_path` 的 parent dir 不存在時，`__init__` 自動 `mkdir(parents=True, exist_ok=True)`。

### 5.4 conv_id 不存在的查詢行為

- `load_conversation("nonexistent")` → raise `KeyError(conv_id)`（明確錯誤，UI 可 catch）
- `delete_conversation` / `rename_conversation` → 不 raise（idempotent）
- `add_message(conv_id, ...)` 若 conv_id 不存在 → FK constraint 觸發 `sqlite3.IntegrityError`，往上拋（caller 應先 `create_conversation`）

### 5.5 與 Tier 1 `app.py` session_state 的關係

本 spec 完全**不**改 `app.py`。Spec 105 才會在 UI 層用 `HistoryStore`：sidebar 啟動時 `list_conversations()` + session 切換時 `load_conversation(...)`。本 spec 階段 store 純粹是 library。

### 5.6 多版本 schema 共存

若使用者升級 codebase 後沿用舊 `history.sqlite`：
- 舊版本沒有的 column / index 由 `CREATE ... IF NOT EXISTS` + `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`（SQLite 3.35+ 支援）處理
- 本 spec v1 schema 不需 migration；若日後改 schema，新加邏輯

### 5.7 WAL 殘留檔

WAL mode 會留下 `.wal` 與 `.shm` 兩個附屬檔；正常關閉時會 checkpoint 回主 DB。`.gitignore` 加 `*.sqlite*` 避免誤 commit。

---

## 6. DTO 欄位設計總表

### Conversation

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `id` | str | Y | UUID4 字串 |
| `title` | str | Y | 可為空字串 |
| `created_at` | datetime | Y | UTC |

### Message

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `id` | int \| None | N（default None） | DB 指派；建立前為 None |
| `conv_id` | str | Y | FK |
| `role` | MessageRole (StrEnum) | Y | `user` / `assistant` |
| `content` | str | Y | renumber 後的 answer 字串 |
| `citations` | list[StoredCitation] | N（default []） | user 訊息為空 list |
| `created_at` | datetime | Y | UTC |

### StoredCitation

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `chunk_id` | str | Y | 與 RetrievedChunk.chunk_id 同 |
| `display_n` | int (≥1) | Y | UI [n] |
| `score` | float | Y | cosine relevance（持久化當時值） |
| `snapshot_text` | str（max 1000） | Y | chunk 內文快照 |

### MessageRole（StrEnum）

| 值 | 用途 |
|---|---|
| `user` | 使用者訊息 |
| `assistant` | LLM 回覆 |

---

## 7. 與外部系統的關係

- **SQLite**：stdlib `sqlite3`；DB 檔位於 `Settings.history_db_path`
- **檔案系統**：parent dir auto-create；WAL `.wal` / `.shm` 附屬檔自然產生
- **不打 LLM、不讀 Chroma**：HistoryStore 是純 storage 層；citation 反查（讀 Chroma）由 UI 層做

---

## 8. Acceptance Criteria

1. **持久化往返**：`store.create_conversation(title="t1")` → `store.add_message(conv.id, "user", "Q?")` → 銷毀 store 實例 → 重 `HistoryStore(path)` → `load_conversation(conv.id)` 回 `(conv, messages)`，其中 `conv.title == "t1"`、`messages[0].content == "Q?"`、`messages[0].role == MessageRole.USER`。
2. **`Settings.history_db_path` 預設 `"./data/history.sqlite"`**：`Settings().history_db_path == "./data/history.sqlite"` 為 True。
3. **FK CASCADE 刪除**：建 1 conv + 3 messages，呼叫 `delete_conversation(conv.id)`，連線重 `SELECT COUNT(*) FROM messages WHERE conv_id = ?` 必回 0。
4. **Snapshot 長度上限**：對 `add_message` 傳 `StoredCitation(snapshot_text="A" * 2000, ...)`，store 端必自動 truncate；讀回 `messages[0].citations[0].snapshot_text` 長度 ≤ 1000 且以 `"…"` 結尾（或 `model_validate` 守門讓寫入時就強制縮短）。
5. **並發不死鎖**：開兩個 thread，A thread 跑 100 次 `add_message`（讀寫），B thread 跑 100 次 `list_conversations`（讀），總時間 < 5 秒、零 exception。
6. **`rename_conversation` 與 `delete_conversation` 對不存在 id 不 raise**：`store.delete_conversation("nope")` / `store.rename_conversation("nope", "x")` 都不 raise。
7. **`load_conversation` 對不存在 id raise KeyError**：`store.load_conversation("nope")` raise `KeyError`。
8. **列表排序**：建立 3 個 conversation（間隔 sleep 10ms 確保時間不同），`list_conversations()` 必依 `created_at DESC` 排序（最新在前）。
9. **role enum 持久化**：`add_message(conv_id, role=MessageRole.ASSISTANT, ...)` 後 SQL 查 `messages.role` 必為字串 `"assistant"`（StrEnum 序列化）。
10. **Schema 鎖死**：對 fixtures 三個 JSON（conversation / message / stored_citation）執行 `Conversation.model_validate(...)`、`Message.model_validate(...)`、`StoredCitation.model_validate(...)` 均不 raise。
11. **WAL 啟用**：建 store 後 `sqlite3.connect(path).execute("PRAGMA journal_mode").fetchone()[0]` 為 `"wal"`。

---

## 9. 與其他 spec 的介面

| 對象 spec | 本 spec 暴露 / 消費什麼 | 對方怎麼用 |
|---|---|---|
| **Spec 100 Migration** | **消費** `CitedChunkRef` 概念（chunk_id + display_n） | `StoredCitation` 是 `CitedChunkRef` + score + snapshot 的擴充；Spec 100 不需改 |
| **Spec 100 Migration** | **消費** `Settings`（在 `src/config.py` 加 `history_db_path` 欄位） | Spec 100 的 `Settings` 類別需保留 `extra="ignore"` 設定（已是 Tier 1 預設） |
| **Spec 102 Loaders** | **消費** `RetrievedChunk.source` 字串（含 XLSX `"#sheet"`） | 照存不解析；Spec 102 不需改 |
| **Spec 104 Quality Eval** | 無直接介面 | quality report 是 query-time evaluation，**不**持久化到 history（v3 backlog） |
| **Spec 105 UI Integration** | **暴露** `HistoryStore` 全部 7 個方法；sidebar 用 `list_conversations` + 切換用 `load_conversation` + delete UI 用 `delete_conversation` | UI 渲染 message 時：先 `fetch_chunks_by_ids(c.chunk_id for c in msg.citations)` 反查 Chroma；未命中用 `c.snapshot_text` fallback（與 Tier 1 `render_citations` 邏輯相同） |

---

## 10. Out of scope（再次強調）

- **多使用者 / auth / RBAC**（**第 2 次重複提醒**）
- **雲端同步**（**第 2 次重複提醒**）
- **全文搜尋對話歷史**（**第 2 次重複提醒**）
- 對話匯出（markdown / pdf / json）
- 對話 fork / branch
- 自動標題生成（LLM-based；只截前 N 字）
- DB migration framework
- 加密 SQLite
- ORM（SQLAlchemy / sqlmodel / peewee）
- 跨 process file locking 完美隔離
- 影響 Tier 1 retrieval / answer 流程
- citation 反查邏輯（仍在 UI 層；store 不知道 Chroma）

---

## 11. 參考

- 重建計畫：`~/.claude/plans/rag-citation-mvp-rag-citation-memoized-locket.md` §「Spec 103 — Chat History Persistence」
- 上游：[Spec 100](../100-migration-foundation/spec.md)、[Spec 102](../102-multi-format-loaders/spec.md)
- 下游：[Spec 105](../105-ui-integration/spec.md)
- SDD 規範：[`specs/CLAUDE.md`](../CLAUDE.md)
- SQLite WAL 文件：https://sqlite.org/wal.html
