# Phase 8 Spec: 文件 + Release

## 目的
產出可讓新使用者順利上手的 README，並把所有變更推到 GitHub。

## README 必含區塊

1. **What**：一句話說明 — 句子級 citation 的 RAG MVP，可追溯到原文。
2. **Why**：對比 NotebookLM / Claude / Perplexity，說明為什麼 sentence-level citation 重要。
3. **架構圖（文字）**：ingest 流程 + query 流程
4. **Installation**：
   - `pip install -r requirements.txt`
   - `cp .env.example .env`
   - `ollama pull qwen2.5:7b` & `ollama serve`
5. **Quickstart**：
   ```bash
   python scripts/ingest.py data/your.pdf
   python scripts/ask.py "你的問題"
   ```
6. **Citation 機制概念**：Perplexity-style 預編號 + Anthropic-style `<CIT>` tag
7. **Project Layout**：specs / src / scripts / tests
8. **SDD + Agent Team**：簡短說明開發流程
9. **Tests**：`pytest` 跑完所有測（mock 為主，含 1 個可選 slow integration）
10. **Limitations**：不做 OCR、不做 Word/PPT 直讀、不做 hybrid retrieval

## Push 流程
1. `git status` 看變更
2. `git add` 個別檔案（避免 `git add .`）
3. `git commit -m "..."` 建立原子 commit（可分多個）
4. **詢問使用者要推 main 還是開 PR**
5. 對應動作：`git push origin main` 或 `gh pr create`

## 驗收
- README 在 GitHub 上 render 看得懂
- `pytest` 全綠
- repo 推上去後 `git@github.com:xian-ai-1057/tag_rag.git` 看得到內容
