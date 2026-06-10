# Tag RAG — Citation MVP

帶 chunk 級 inline `[n]` 引用的本地 RAG demo。

- LLM / Embedding：本地 Ollama（OpenAI 相容介面）
- Vector store：ChromaDB persistent（免 Docker）
- UI：Streamlit
- 支援格式：PDF / DOCX / XLSX / HTML / Markdown / TXT（Tier 2 完整支援）

## 系統概觀（白話版）

用「圖書館 + 助理」的比喻：把文件丟進「資料櫃」、提問時「助理」會去查資料、找出答案並附上「資料出處」。

```mermaid
flowchart TD
    subgraph Step1["📚 步驟一：把資料放進系統"]
        A1[📄 上傳文件<br/>PDF / Word / Excel / 網頁 / 文字檔] --> A2[✂️ 系統自動<br/>把長文件切成小段]
        A2 --> A3[🗂️ 建立索引<br/>幫每段內容貼上標籤<br/>方便日後查找]
        A3 --> A4[(📦 知識櫃<br/>儲存所有資料)]
    end

    subgraph Step2["💬 步驟二：提問與回答"]
        B1[🙋 使用者輸入問題] --> B2[🔍 系統去知識櫃<br/>找出最相關的幾段資料]
        B2 --> B3[🤖 AI 助理閱讀這些資料<br/>整理出一段回答]
        B3 --> B4[📎 自動標註資料來源<br/>方便使用者查證]
        B4 --> B5[✅ 顯示答案 + 出處<br/>例如：根據文件 A 第 3 頁]
    end

    subgraph Step3["🛡️ 步驟三：品質把關與記錄"]
        C1[📊 自動評估答案品質<br/>檢查是否真的有出處支持<br/>標記可能編造的內容]
        C2[💾 對話自動保存<br/>可隨時回顧過去問答]
    end

    A4 -.->|提供資料| B2
    B5 --> C1
    B5 --> C2

    style Step1 fill:#e3f2fd
    style Step2 fill:#f3e5f5
    style Step3 fill:#fff3e0
```

**三句話總結**：
1. **餵資料**：把公司文件丟進系統，它會自動切段、建索引存進「知識櫃」。
2. **問答案**：使用者問問題，AI 從知識櫃找資料、寫出帶有「來源頁碼」的答案。
3. **可信賴**：系統會自動檢查答案是否有依據、會不會亂講，並保留對話紀錄。

## 啟動步驟

```bash
# 0. 安裝 Ollama 並 pull 模型（一次性）
brew install ollama && brew services start ollama
ollama pull gemma4:e4b      # LLM（預設；中文友善的替代選擇：qwen3.5:9b / qwen3:8b）
ollama pull bge-m3          # embedding（多語）

# 1. Python 環境
uv venv && source .venv/bin/activate
uv pip install -e .

# 2. 設定環境變數
cp .env.example .env        # 預設值即可，要換模型再改

# 3. 啟動
streamlit run app.py
```

## 使用流程

1. 開啟瀏覽器（Streamlit 預設 `http://localhost:8501`）
2. 在左側欄「📥 文件管理」區塊上傳 PDF / DOCX / XLSX / HTML / MD / TXT，按「入庫」
3. 按「新對話」開始新的對話，或從對話歷史切換現有對話
4. 在「💬 問答」分頁提問
5. 答案會以 `[1][2]` 形式 inline 標註，展開「📚 引用來源」面板檢視每個編號對應的原文片段
6. 使用側欄 Sidebar 重命名或刪除對話

## 格式支援

| 格式 | 說明 |
|------|------|
| **PDF** | 全文逐頁擷取，每頁產一個 document（含 page metadata） |
| **DOCX** | 段落與標題層級保留，內容按邏輯分段 |
| **XLSX** | 每個 sheet 逐行掃描，每 50 列重複欄位名稱以保持上下文，支援公式評估值 |
| **HTML** | 過濾 script / style 等噪音標籤，保留 p / div / li / blockquote 等內容元素 |
| **Markdown** | 標題層級與代碼塊結構保留，內容按語義分段 |
| **TXT** | 純文字逐行讀入，簡單分段 |

## 對話歷史

- 所有對話自動持久化到 `./data/history.sqlite`
- 跨瀏覽器 session 保留歷史（重整頁面、關閉重啟仍可回復）
- UI 左側欄 Sidebar 可：
  - 切換現有對話
  - 重命名對話標題
  - 刪除對話（含消息歷史）

## 品質評估

每條回答會自動執行品質評估，包括：

- **Quality Score**：基於句級 support 與實體幻覺偵測的綜合評分
- **Sentence Support**：每句話評估是否有對應的檢索出來的 chunk 支持
- **Entity Hallucination**：使用規則型 regex 匹配（人名、數字、日期、組織名等），標記可能編造的實體

評估邏輯為 Deterministic、純規則基礎、執行時間 < 500ms，無依賴 LLM 的額外呼叫。

## 測試

```bash
pytest tests/unit -q                               # 純單元測試（LLM 全 mock）
pytest tests/integration -q -m "not requires_ollama"  # 整合測試（不需 Ollama 的部分）
bash scripts/regression.sh                         # 一次跑完上述兩者
pytest tests/integration -q -m requires_ollama     # 需本機 Ollama 啟動時才跑
```

- 所有 LLM 呼叫測試一律 **mock**，預設不打真 Ollama，可離線執行。
- `conftest.py` 註冊 `requires_ollama` marker，標記需要本機 Ollama 實例的整合測試。
- 涵蓋範圍：chunking、citation renumber、各 loader（docx / xlsx / html）、eval（support / entities）、history store，以及端到端 pipeline。

## 系統流程圖（技術版）

### 高層架構

```mermaid
flowchart LR
    User([👤 User])
    UI[Streamlit UI<br/>app.py]

    subgraph Core["RAG Core (src/)"]
        Ingest[Ingest Pipeline<br/>src/ingest.py]
        Loaders[Loaders<br/>src/loaders/*]
        Chunker[Chunker<br/>src/chunking.py]
        Retriever[Retriever<br/>src/retrieval.py]
        Chain[RAG Chain<br/>src/rag_chain.py]
        Prompts[Prompts<br/>src/prompts.py]
        LLMFactory[LLM Factory<br/>src/llm.py]
        Citation[Citation Renumber<br/>src/citation.py]
        Eval[Quality Eval<br/>src/eval/*]
        History[(History Store<br/>src/history/*)]
    end

    subgraph External["External Services"]
        Ollama[/Ollama<br/>LLM + Embedding/]
        Chroma[(ChromaDB<br/>data/chroma/)]
        SQLite[(SQLite<br/>data/history.sqlite)]
    end

    User <--> UI
    UI -->|upload| Ingest
    UI -->|question| Chain
    Ingest --> Loaders --> Chunker --> Chroma
    Chunker -->|embed| Ollama
    Chain --> Retriever --> Chroma
    Chain --> Prompts
    Chain --> LLMFactory -->|LLM call| Ollama
    Chain --> Citation
    Chain --> Eval
    UI <--> History --> SQLite
```

### Ingest 流程（文件入庫）

```mermaid
flowchart TD
    A[User 上傳檔案<br/>app.py: render_doc_tab] --> B[ingest_paths paths<br/>src/ingest.py]
    B --> C{副檔名分派<br/>src/loaders/__init__.py: load_file}

    C -->|.pdf| D1[load_pdf]
    C -->|.docx| D2[docx_loader.load]
    C -->|.xlsx| D3[xlsx_loader.load]
    C -->|.html| D4[html_loader.load]
    C -->|.md / .txt| D5[load_text]

    D1 & D2 & D3 & D4 & D5 --> E[list of Document<br/>含 source / page metadata]
    E --> F[chunk_documents<br/>RecursiveCharacterTextSplitter<br/>size/overlap 由 CHUNK_SIZE/CHUNK_OVERLAP 設定<br/>預設 512/128]
    F --> G[加入 stable metadata:<br/>doc_id = MD5 source first10<br/>chunk_index = 0..N<br/>page]
    G --> H[vs.add_documents<br/>ids = doc_id:chunk_index]
    H --> I[Ollama embedding<br/>bge-m3]
    I --> J[(ChromaDB<br/>persist)]
    J --> K[回傳 chunk 總數]
```

關鍵：chunk_id 為 `{doc_id}:{chunk_index}` 穩定字串，重新 ingest 不會疊加且引用維持 stable ref。

### Query / RAG 流程（提問 → 答案）

```mermaid
flowchart TD
    Q[User 輸入問題<br/>app.py: render_chat_tab] --> R[query question<br/>src/rag_chain.py]

    R --> S[retrieve question, k=5<br/>src/retrieval.py]
    S --> S1[(ChromaDB<br/>similarity_search<br/>with_relevance_scores)]
    S1 --> S2[list of RetrievedChunk<br/>n=1..k, chunk_id, text,<br/>source, page, score]

    S2 --> T[Prompt 組裝<br/>src/prompts.py: build_user_message<br/>_BLOCK_TEMPLATE per chunk<br/>_USER_TEMPLATE 包含 context + question]
    T --> U[LLM 呼叫<br/>src/llm.py: _get_llm<br/>Ollama LLM（LLM_MODEL，預設 gemma4:e4b）]
    U --> V[原始 answer<br/>含 inline n 標記<br/>可能含 fabricated n]

    V --> W[renumber_and_filter<br/>src/citation.py]
    W --> W1{regex 掃描 n}
    W1 -->|n in retrieved| W2[依首次出現順序 remap]
    W1 -->|n 超出範圍| W3[移除 fabricated 標記]
    W2 & W3 --> X[最終 answer<br/>標記改為 1..M 連號]

    X --> Y[RagAnswer<br/>answer + citations + retrieved]

    Y --> Z1[render markdown + citations<br/>app.py: render_citations]
    Y --> Z2[evaluate ans<br/>src/eval]
    Y --> Z3[HistoryStore.add_message<br/>persist 到 SQLite]

    Z2 --> Z2a[QualityReport<br/>sentence support + hallucination]
    Z3 --> Z3a[(SQLite)]
```

範例：LLM 產出 `[2][4][2][99]` → filter 後 `[1][2][1]`，citations 依新順序排列、`.n` 欄位更新。

### 對話歷史 & 引用渲染

```mermaid
flowchart LR
    subgraph Save["儲存（query 後）"]
        A1[RagAnswer.citations] --> A2[StoredCitation<br/>chunk_id / display_n / score /<br/>snapshot_text 截斷 1000 chars]
        A2 --> A3[HistoryStore.add_message<br/>JSON 序列化]
        A3 --> A4[(messages 資料表)]
    end

    subgraph Load["載入（切換對話）"]
        B1[User 點選 conversation] --> B2[load_conversation conv_id]
        B2 --> B3[反序列化 messages + citations]
        B3 --> B4[render_citations]
    end

    subgraph Render["引用渲染（每條 citation）"]
        C1[citation.chunk_id] --> C2[fetch_chunks_by_ids]
        C2 --> C3{chunk 仍在 Chroma?}
        C3 -->|是| C4[顯示 live text + 完整 metadata]
        C3 -->|否 stale| C5[fallback 顯示 snapshot_text]
        C4 & C5 --> C6[format:<br/>n source · page · chunk_index · score]
    end

    B4 --> Render
```

## 設計重點

- **Chunk 級 citation**：每個 retrieved chunk = 1 個 citable unit（仿 Anthropic custom-content）
- **Context-assembly 階段建好編號↔chunk 映射**（仿 Perplexity），非生成後 retrofit
- **Prompt-based `[n]` marker**（仿 LlamaIndex CitationQueryEngine），regex 解析後過濾編造編號
- **Deterministic chunk id**：同檔案重複 ingest 不會疊加（`{doc_id}:{chunk_index}`）
- **本地優先**：完全跑在本機，無需任何雲端 API key

## 已知限制（Tier 2）

- 無 streaming 支援（全部答案生成完再展示）
- 無多使用者隔離（共用同一向量庫與對話庫）
- 要刪向量庫請手動 `rm -rf data/chroma/`；要清空對話請刪除 `data/history.sqlite`

## 結構

```
.
├── pyproject.toml
├── .env.example
├── CLAUDE.md            # 專案指南（給 Claude / teammate）
├── conftest.py          # pytest 設定（註冊 requires_ollama marker）
├── rag.py               # Tier 1 façade（re-export src.*）
├── app.py               # Streamlit UI
├── src/
│   ├── config.py        # 環境變數與設定（Pydantic Settings）
│   ├── logging_setup.py # logging 設定，noisy lib 壓到 WARNING
│   ├── ingest.py        # 檔案入庫 pipeline
│   ├── chunking.py      # RecursiveCharacterTextSplitter 切段
│   ├── llm.py           # LLM factory（指向 Ollama 的 ChatOpenAI）
│   ├── prompts.py       # SYSTEM_PROMPT / templates / build_user_message
│   ├── rag_chain.py     # RAG query chain
│   ├── citation.py      # inline [n] 引用重新編號與過濾
│   ├── retrieval.py     # 向量檢索與 chunk 管理
│   ├── vectorstore.py   # ChromaDB 操作層（client 以 settings 值快取）
│   ├── utils.py         # 跨模組共用：CITE_RE / preview
│   ├── loaders/         # PDF / DOCX / XLSX / HTML / Text 載入器
│   ├── history/         # SQLite 對話持久化與管理
│   └── eval/            # 品質評估 & hallucination 偵測
├── tests/
│   ├── unit/            # 單元測試（chunking / citation / loaders / eval / history）
│   ├── integration/     # 端到端 pipeline 測試
│   └── fixtures/        # 測試用文件與 snapshot
├── scripts/
│   └── regression.sh    # 一次跑完 unit + 非 Ollama 整合測試
├── specs/               # SDD 規格與 contracts
└── data/
    ├── docs/            # 來源檔（含 demo.md）
    ├── chroma/          # Chroma persistent dir（git ignore）
    └── history.sqlite   # 對話歷史（git ignore）
```
