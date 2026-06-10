"""Prompt strings（byte-identical to Tier 1 rag.py）+ user message 組裝。"""
from src.retrieval import RetrievedChunk

SYSTEM_PROMPT = """你是一個嚴謹的問答助理。你會收到使用者問題與多段【參考資料】，每段以 [n] 編號標示。

【作答規則】
1. 只能使用提供的參考資料；不得編造資訊。
2. 每段論述結尾必須標註來源編號，例如 [1] 或 [2][3]。
3. 若同一句話綜合多段資料，依重要性排序列出所有編號。
4. 若參考資料不足以回答問題，明確說「依現有資料無法回答」並指出缺什麼。
5. 使用繁體中文回答。
6. 不要在回答尾端加入「參考資料」、「來源清單」等清單 — 介面下方會另行顯示。"""

_USER_TEMPLATE = """【參考資料】
{context_blocks}

【使用者問題】
{question}

【回答】"""

_BLOCK_TEMPLATE = "[{n}] 來源: {filename}（第 {page} 頁）\n{content}\n"


def build_user_message(chunks: list[RetrievedChunk], question: str) -> str:
    context = "\n".join(
        _BLOCK_TEMPLATE.format(n=c.n, filename=c.filename, page=c.page, content=c.content)
        for c in chunks
    )
    return _USER_TEMPLATE.format(context_blocks=context, question=question)
