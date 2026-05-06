# Phase 0 Spec: 專案骨架

## 目的
建立可安裝、可測試的 Python 專案骨架，讓後續每階段都能在統一結構下加程式與測試。

## 目錄結構
```
tag_rag/
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
├── pytest.ini
├── specs/                # 各階段 spec
├── src/                  # 程式碼 (套件名 tag_rag)
│   ├── __init__.py
│   ├── config.py
│   ├── loaders.py        # 空殼
│   ├── splitter.py       # 空殼
│   ├── embedder.py       # 空殼
│   ├── vector_store.py   # 空殼
│   ├── prompt.py         # 空殼
│   ├── citation_parser.py# 空殼
│   ├── llm.py            # 空殼
│   └── rag.py            # 空殼
├── scripts/
│   ├── ingest.py
│   └── ask.py
├── data/                 # 範例文件存放區
└── tests/
    ├── __init__.py
    ├── conftest.py
    └── fixtures/
```

## 套件依賴（requirements.txt）
- `pypdf` — PDF 文字抽取
- `beautifulsoup4` — HTML 解析
- `lxml` — bs4 backend
- `pymilvus` — Milvus client（含 Lite 模式）
- `FlagEmbedding` — BGE-M3
- `openai` — LLM client（指 Ollama）
- `python-dotenv` — env loader
- `numpy`
- `pytest`
- `pytest-mock`

## .env.example 內容
```
OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_MODEL=qwen2.5:7b
OLLAMA_API_KEY=ollama
MILVUS_URI=./milvus.db
MILVUS_COLLECTION=tag_rag
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_DIM=1024
TOP_K=5
```

## config.py
從環境讀以上變數，提供 `Config` dataclass。

## 驗收標準
- `pip install -r requirements.txt` 在 Python 3.10+ 成功
- `pytest` 可跑（即使 0 tests），exit code 0
- 所有 `src/*.py` 至少存在且可 `import tag_rag.<module>`
- `.gitignore` 包含 `milvus.db` 與 `data/*.pdf` 以外（範例 fixture 不入 git，但 `data/.gitkeep` 保留）

## 不在範圍內
- 任何業務邏輯（後續階段才寫）
- CI 設定
