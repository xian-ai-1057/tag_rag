# Tag RAG — Project Guide for Claude

## What this is

帶 chunk 級 inline `[n]` 引用的本地 RAG demo，作為 Taishin 內部知識庫 RAG 雛形。

- **LLM / Embedding**：本地 Ollama（OpenAI 相容介面 `http://localhost:11434/v1`）
- **Vector store**：ChromaDB PersistentClient（免 Docker）
- **UI**：Streamlit
- **支援格式**：Tier 1 = PDF / MD / TXT；Tier 2 加 DOCX / XLSX / HTML

## 開發狀態

| Tier | 範圍 | 狀態 |
|------|------|------|
| Tier 1 | 核心 RAG + chunk_id stable refs + renumber | ✅ Done（`rag.py` + `app.py`） |
| Tier 2 | SDD 拆模組 + 多格式 loader + chat history + quality eval | ✅ Done |
| Tier 3 | Streaming / 多使用者隔離 / OCR / URL fetch | 📋 Backlog |

詳見：
- 完整計畫：[~/.claude/plans/rag-citation-mvp-rag-citation-memoized-locket.md](/Users/kee/.claude/plans/rag-citation-mvp-rag-citation-memoized-locket.md)
- Spec 結構：[specs/CLAUDE.md](specs/CLAUDE.md)
- Phase / Team 配置：[specs/agent-teams-plan.md](specs/agent-teams-plan.md)

## 查詢管線（query pipeline）

`src/rag_chain.py::query()` 是唯一入口，支援**雙路徑**：

1. **本地檢索**（`reranked=None`）— 呼叫 `retrieval.py::retrieve()` 對 Chroma 做
   `similarity_search_with_relevance_scores`，輸出對齊外部 RAG 的 **arrkb schema**
   （`RerankedChunk`）。
2. **外部注入**（`reranked=[...]`，「arrkb 路徑」）— 直接餵入外部 production RAG 的
   reranked 結果（`list[dict]` 或 `list[RerankedChunk]`），跳過本地檢索。
   範例輸入見 [data/sample_reranked.json](data/sample_reranked.json)。

兩條路徑都先 `coerce_reranked()` → `RerankedChunk` → `to_retrieved_chunk()` →
`RetrievedChunk`，組 context block 後以 `temperature=0` 呼叫 LLM，再由
`citation.py::renumber_and_filter` 只保留答案實際引用的 chunk 並 renumber 為 `1..N`，
回傳 `RagAnswer`（`answer` / `citations` / `retrieved`）。

## 啟動

```bash
# 一次性設定 — Ollama 與模型
brew install ollama && brew services start ollama
ollama pull qwen3.5:9b      # LLM（中文友善；或 gemma4:e4b / qwen3:8b）
ollama pull bge-m3          # embedding（多語）

# Python 環境
uv venv && source .venv/bin/activate
uv pip install -e .

# 設定
cp .env.example .env        # 預設值即可；要啟用 chat history 需檢查 HISTORY_DB_PATH

# 啟動 UI
streamlit run app.py

# CLI smoke test
python -c "from rag import ingest_paths, query; ingest_paths(['data/docs/demo.md']); result = query('問題'); print(result.answer)"

# 測試（LLM/embeddings 皆 mock，僅 integration smoke 需真 Ollama）
pytest                       # 全部
pytest tests/unit            # 單元
pytest tests/integration     # 整合（test_pipeline_smoke_with_ollama 需 Ollama）
```

## 程式碼風格

- Python 3.11+，type hints 用 `str | None` 而非 `Optional[str]`
- DTO 全用 Pydantic v2（`model_config = ConfigDict(extra="forbid")`）
- Logging：用 `logging.getLogger("rag")` / `logging.getLogger("src.<module>")`，noisy lib（langchain/httpx/chromadb）壓到 WARNING
- Default no comments — code 自我解釋；只在非顯然的 invariants / workarounds 加單行註解
- **不**寫 docstring 給每個 function；只寫 module-level + 複雜邏輯（如 `_renumber_and_filter`）
- 新模組放 `src/<feature>/`，每個子目錄均需 `__init__.py` 暴露公開 API（含 `__all__`）

## SDD 規則（給 teammate）

- `specs/<NNN>-<name>/spec.md` 是單一事實。發現 spec 漏洞 → message Lead 改 spec，不自行解讀
- `specs/<NNN>-<name>/contracts/` 鎖死介面，任何修改回報 Lead
- 兩位 teammate 不可動同一檔案；超界用 mailbox 重新分配
- LLM 呼叫測試一律 mock，不打真 Ollama
- 不寫入 `Archive/`（目前無此目錄，但保留禁令）

## 重點檔案

| 檔案/目錄 | 用途 |
|----------|------|
| [rag.py](rag.py) | Tier 1 façade（`src.*` re-export） |
| [app.py](app.py) | Streamlit UI |
| [src/config.py](src/config.py) | 環境變數與設定（Pydantic Settings） |
| [src/loaders/](src/loaders/) | 多格式載入器（PDF / DOCX / XLSX / HTML / Text） |
| [src/history/](src/history/) | SQLite 對話持久化與管理 |
| [src/eval/](src/eval/) | 品質評估與 hallucination 偵測 |
| [src/ingest.py](src/ingest.py) | 檔案入庫 pipeline |
| [src/rag_chain.py](src/rag_chain.py) | `query()` 雙路徑 orchestrator（本地檢索 / arrkb 注入）+ citation renumbering |
| [src/retrieval.py](src/retrieval.py) | 向量檢索 + arrkb schema（`RerankedChunk` / `RetrievedChunk`）正規化 |
| [src/citation.py](src/citation.py) | `renumber_and_filter` — 只留實際引用的 chunk 並重編號 |
| [src/vectorstore.py](src/vectorstore.py) | ChromaDB 操作層 |
| [specs/](specs/) | SDD 規格與 contracts |
| [tests/](tests/) — pytest 單元與整合測試 |
| [data/docs/](data/docs/) | 來源文件（含 demo.md） |
| [data/sample_reranked.json](data/sample_reranked.json) | arrkb 路徑範例輸入（外部 reranked 結果） |
| [data/chroma/](data/chroma/) | Chroma persistent dir（git ignore） |
| [data/history.sqlite](data/history.sqlite) | 對話歷史（git ignore） |
