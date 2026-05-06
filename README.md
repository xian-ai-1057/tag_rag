# tag_rag

**Sentence-level citation RAG MVP** — 每個生成 claim 都能反查到原文的特定句子（含檔名、頁碼、char offset、原句文字）。

## Why

NotebookLM、Claude Citations API、Perplexity 都把 sentence-level citation 當成核心差異化能力 — 它能大幅降低 hallucination 並讓使用者驗證答案。本專案在**本機 LLM** 環境下複現這個能力，採用：

- **Perplexity-style preassignment**：retrieval 完就把每個 chunk 的句子預先編號 `[chunk_id=N] s0:... s1:...` 塞進 prompt
- **Anthropic-style tag output**：要求 LLM 用 `<CIT c="X" s="Y">claim</CIT>` 包裹每個事實聲明
- **Regex parser + 反查**：把 tag 對應回 retrieval hit 內保留的完整 sentence metadata（含 char offset、page、source_path）

## Architecture

```
ingest:
  file → loader (PDF/txt/md/html, 保留頁碼)
       → sentence splitter (中英文混排, 保留 char offset)
       → chunk builder (對齊句子邊界, 保留 sentences[])
       → BGE-M3 embed
       → Milvus Lite (vector + JSON metadata 含 sentences)

query:
  question → BGE-M3 embed → Milvus top-k hits
           → prompt：[chunk_id=0] s0:... s1:... 預編號塞給 LLM
           → Ollama (透過 OpenAI SDK)
           → 回傳 <CIT c="0" s="1">claim</CIT> 句子
           → regex parser → AnswerWithCitations
              (clean_answer + citations[{source_path, page, char_range, sentence_text}])
```

## Installation

```bash
pip install -r requirements.txt
cp .env.example .env

# 啟動本機模型
ollama pull qwen2.5:7b
ollama serve  # 另一個 shell
```

`.env.example` 列出所有可調環境變數（Ollama base URL、Milvus URI、embedding model 等）。

## Quickstart

```bash
# 1. 把文件 ingest 進向量庫
python scripts/ingest.py data/sample.pdf data/notes.md

# 2. 提問，得到帶 citation 的答案
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

## Project Layout

```
specs/    — Spec Guardian 為每階段寫的 spec
src/      — Dev 的實作 (loaders, splitter, embedder, vector_store, prompt, llm, citation_parser, rag)
scripts/  — CLI 入口 (ingest.py, ask.py)
tests/    — QA 寫的單元測試
data/     — 範例文件存放
```

## Development: SDD + Agent Team

開發採 **Spec-Driven Development**：

| 角色 | 職責 |
|---|---|
| Spec Guardian | 寫每階段 spec、最終驗收 |
| QA | 依 spec 設計 unit test |
| Dev | 依 spec 實作程式碼通過測試 |

每階段循環：spec → tests（紅）→ impl（綠）→ 驗收。完整 spec 在 [`specs/`](specs/)。

## Tests

```bash
pytest                    # 全部（不含 slow）
pytest -m slow            # 真打 BGE-M3 + Ollama 的整合測試
pytest -v tests/test_X.py # 單一階段
```

預設 100+ unit tests 全綠。Embedder / LLMClient 用 monkeypatch 隔離；VectorStore 用 Milvus Lite tmp file 隔離；其餘 (loaders / splitter / citation_parser) 用真實算法測。

## LLM swap

LLM client 寫成 OpenAI 相容 endpoint：

```python
from src.llm import LLMClient
client = LLMClient(
    base_url="http://your-vllm-server:8000/v1",
    api_key="...",
    model="your-model",
)
```

換 vLLM、OpenAI 雲端、其他相容 server 不用改其他模組。

## Limitations

- **不做** Word / PPT 直讀（請外部轉成 txt/PDF）
- **不做** OCR — 沒有文字層的掃描 PDF 會發 warning 並跳過
- **不做** hybrid retrieval (BM25 + dense)，目前 dense-only
- **不做** multi-turn 對話歷史
- **不做** 前端 UI（後續再開）
- 8B 等級本機模型對 `<CIT>` tag 格式遵循度不如 GPT-4 / Claude；如果輸出格式飄掉可換大模型或換 Anthropic Citations API
