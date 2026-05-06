# Phase 5 Spec: LLM Client + Citation Prompt

## 目的
1. 提供一個用 OpenAI Python SDK（指向 Ollama base URL）的薄 client，未來可換 vLLM / OpenAI 而不動其他模組。
2. 提供 prompt builder：把 retrieved chunks 用 **「Perplexity-style 預編號」** 方式組成 user prompt，搭配 system prompt 強制 LLM 用 `<CIT c="X" s="Y">claim</CIT>` 格式輸出。

## 公開介面

```python
# src/llm.py
from __future__ import annotations
from openai import OpenAI

class LLMClient:
    def __init__(
        self,
        base_url: str = "http://localhost:11434/v1",
        api_key: str = "ollama",
        model: str = "qwen2.5:7b",
        temperature: float = 0.0,
    ) -> None: ...

    def chat(self, messages: list[dict]) -> str:
        """Send chat completion; return assistant text content."""
        ...
```

```python
# src/prompt.py
from __future__ import annotations
from src.vector_store import ChunkHit

CITATION_SYSTEM_PROMPT: str  # 公開常數，方便測試與 debug

def build_citation_messages(
    question: str,
    chunks: list[ChunkHit],
) -> list[dict]:
    """Return [{"role":"system",...},{"role":"user",...}]."""
    ...

def render_chunks_block(chunks: list[ChunkHit]) -> str:
    """Render the chunks portion of the user prompt (testable in isolation)."""
    ...
```

## Prompt 結構

### System prompt（CITATION_SYSTEM_PROMPT）
英文書寫（多數本機 LLM 對英文 system instruction 比中文穩），但要求模型可以用問題語言回答：

```
You are a careful research assistant. Answer the user's question USING ONLY the
sources provided below. For every factual claim, wrap it in a citation tag of
the form:

  <CIT c="<chunk_id>" s="<sentence_id>">your phrasing of the claim</CIT>

Citation rules:
- chunk_id and sentence_id MUST refer to a chunk and sentence that actually
  appears in the Sources section.
- For a single supporting sentence: s="3"
- For a contiguous range: s="3-5"
- For multiple non-contiguous sentences from the same chunk: s="1,4"
- If a claim needs evidence from multiple chunks, use multiple <CIT> tags.
- DO NOT invent citations. If the sources do not support an answer, reply:
  "I could not find this in the provided sources." (in the same language as
  the question).
- Use the same language as the question for the answer text.
- Keep claims concise; one <CIT> per claim is preferred.
```

### User prompt 結構

```
Sources:
[chunk_id=0] (from <basename(source_path)>, page <page>)
  s0: <sentence text>
  s1: <sentence text>
  ...

[chunk_id=1] (from <basename(source_path)>, page <page>)
  s0: ...

Question: <question>
```

注意事項：
- `chunk_id` 在 prompt 內**重新編號為 0..N-1**（用 chunks 的順序），不是用 ChunkHit.chunk_id（後者是文件內的序號，不同文件可能撞）
- `sentence_id` 也用 chunk 內 0..M-1 重編號（從每個 chunk 的 sentences 陣列順序）
- `from <basename>` 取 `Path(source_path).name`，找不到 source_path 時用 `chunk.doc_title or chunk.doc_id`
- `page <page>` 取每個 chunk 第一個句子的 page；無 page 則省略整段 `, page X`
- 若 chunk 沒 sentences（理論上不會），fallback 用 `s0: <chunk_text 的前 200 字>`

**重要**：返回的 prompt 是給 LLM 看的；後續 Phase 6 的 parser 必須能從 `<CIT c="0" s="1">` 對應回 `chunks[0].sentences[1]`。本階段的 chunks list 順序就是 parser 的索引基準。

## LLMClient 行為

- `__init__` 立刻建立 `OpenAI(base_url=base_url, api_key=api_key)` instance
- `chat(messages)`：呼叫 `client.chat.completions.create(model, messages, temperature)`，回傳 `response.choices[0].message.content`
- 失敗（連線錯、模型不存在）→ 讓底層例外往上拋，由呼叫端處理
- 預設 `temperature=0.0`（citation 任務需要確定性）

## 驗收標準

### prompt.py
1. test_render_chunks_block_basic — 兩個 chunks，每個 2-3 句；輸出包含 `[chunk_id=0]`、`[chunk_id=1]`、`s0:`、`s1:` 字串
2. test_render_chunks_block_includes_filename — chunk 有 source_path=`/abs/path/foo.pdf` → 輸出含 `from foo.pdf`
3. test_render_chunks_block_includes_page — chunk 第一句有 page=5 → 輸出含 `page 5`
4. test_render_chunks_block_no_page_when_none — page=None → 輸出不含 `, page`
5. test_render_chunks_block_uses_doc_title_when_no_path — source_path="" + doc_title="My Doc" → 含 `from My Doc`
6. test_build_citation_messages_structure — 回傳 list 長度 2、第 0 個 role=system 且包含關鍵字 `<CIT`、第 1 個 role=user 且包含 `Sources:` 與 `Question:`
7. test_chunks_renumbered_from_zero — 即使輸入 chunks 的 chunk_id 是 7、3，prompt 內仍是 `[chunk_id=0]`、`[chunk_id=1]`（順序為輸入順序）
8. test_sentences_renumbered_from_zero — sentences 在 prompt 內 `s0`, `s1`...
9. test_empty_chunks_block — 空 list → 用 placeholder `(no sources retrieved)` 但仍回合法 messages

### llm.py
全部 mock，不打真 Ollama：
1. test_llm_client_init_uses_base_url — 用 `monkeypatch.setattr("src.llm.OpenAI", FakeOpenAI)`，斷言 FakeOpenAI 收到的 base_url 與 api_key 與構造參數相符
2. test_chat_returns_message_content — FakeOpenAI 的 `chat.completions.create` 回 mock response，斷言 client.chat 回的字串是 `choices[0].message.content`
3. test_chat_passes_temperature_and_model — 驗證 create 被呼叫時 model/temperature/messages 傳對
4. test_chat_propagates_exceptions — FakeOpenAI 拋例外 → LLMClient.chat 也拋

可選 slow integration test：
- @pytest.mark.slow test_chat_against_ollama — 真打 localhost Ollama，驗證能拿到字串。預設不跑。

## 不在範圍內
- streaming（這版不做）
- function calling
- multi-turn 歷史管理
- prompt cache（本機 LLM 通常不需要）
