# Phase 6 Spec: Citation Parser

## 目的
從 LLM 回應中解析 `<CIT c="X" s="Y">claim</CIT>` tag，**對照 retrieval 階段的 chunks（同一份 list）反查到原文句子**，組成可顯示給使用者的 `AnswerWithCitations`。

## 公開介面

```python
# src/citation_parser.py
from __future__ import annotations
from dataclasses import dataclass
from src.vector_store import ChunkHit

@dataclass(frozen=True)
class Citation:
    ref_num: int                  # 1-indexed，使用者看到的 [1] [2] 編號
    claim_text: str               # LLM 在 tag 內寫的 claim 文字
    chunk_id: int                 # prompt 中的 chunk_id（即 chunks list 的 index）
    sentence_ids: list[int]       # prompt 中的 sentence id 列表（已展開：1-3 → [1,2,3]）
    source_path: str              # 來自 ChunkHit
    doc_id: str
    doc_title: str | None
    page: int | None              # 取第一個對應 sentence 的 page
    sentence_text: str            # 把對應的 sentence dicts 的 text 用空格 join
    char_start: int | None        # 對應 sentence 的最小 char_start（None 若全部缺失）
    char_end: int | None          # 對應 sentence 的最大 char_end

@dataclass(frozen=True)
class AnswerWithCitations:
    clean_answer: str             # 去掉 <CIT> tag 後的純文字答案，但保留 [N] 編號
    citations: list[Citation]     # 依出現順序、ref_num 從 1 起

def parse_citations(raw: str, chunks: list[ChunkHit]) -> AnswerWithCitations: ...
```

## 解析規則

### Regex
```python
CIT_PATTERN = re.compile(
    r'<CIT\s+c=["\'](\d+)["\']\s+s=["\']([\d\-,\s]+)["\']\s*>(.*?)</CIT>',
    re.DOTALL,
)
```

### sentence id 展開
- `"3"` → `[3]`
- `"3-5"` → `[3, 4, 5]`（含頭含尾）
- `"1,4"` → `[1, 4]`
- `"1, 3-5, 7"` → `[1, 3, 4, 5, 7]`
- 範圍逆序 `"5-3"` → 視為單一錯誤，紀錄 warning 但不爆，回傳 `[3, 4, 5]`（自動正規化）
- 解析失敗（含非數字） → 整個 tag 降級為純文字（不形成 Citation），warning

### 對照 chunks
- `chunk_id` 是 prompt 中的 chunk_id，**直接當 list index** 用：`chunks[chunk_id]`
- 若 `chunk_id >= len(chunks)` 或 `< 0` → tag 降級為純文字、warning
- `sentence_id` 是 chunk.sentences 內的 0-indexed 索引；若超出 `len(chunks[chunk_id].sentences)` → 該 sentence_id 跳過、warning；若全部跳過 → 整 tag 降級

### clean_answer 組裝
- 把每個合法 `<CIT ...>claim</CIT>` 替換為 `claim [N]`，N 是 1-indexed citation ref_num（按 tag 出現順序）
- 不合法 / 降級的 tag：替換為其內部 `claim` 文字（不附編號）
- 非 tag 區塊原樣保留
- 多空白不額外處理

### Citation 內容組裝
- `claim_text` = tag 內文字（trim 前後空白）
- `chunk_id` = prompt 中數字
- `sentence_ids` = 展開後的整數列表（升冪去重）
- `source_path` / `doc_id` / `doc_title` 直接從 `chunks[chunk_id]` 取
- `sentence_text` = `" ".join(chunks[chunk_id].sentences[i]["text"] for i in valid_sids)`（保持輸入順序，不重排）
- `page` = `chunks[chunk_id].sentences[valid_sids[0]].get("page")` 若存在；否則 None
- `char_start` = min over valid sids 的 char_start；`char_end` = max
- 若 valid_sids 空（所有 sids 都越界） → 整 tag 降級

## 不變式
- `len(result.citations)` == 合法 tag 數量
- `result.citations[i].ref_num` == i + 1
- `result.clean_answer` 不含 `<CIT` 或 `</CIT>` 子字串
- 同一份 raw 兩次 parse 結果完全一致（pure function）

## 驗收標準

`tests/test_citation_parser.py`：

1. test_parse_single_citation — `'<CIT c="0" s="1">grass is green</CIT>'` → 1 citation, ref_num=1, sentence_ids=[1]; clean_answer="grass is green [1]"
2. test_parse_range — `s="2-4"` → sentence_ids=[2,3,4]
3. test_parse_list — `s="1,3"` → [1,3]
4. test_parse_mixed_list_range — `s="1, 3-5, 7"` → [1,3,4,5,7]
5. test_invalid_chunk_id_falls_back — `c="99"` 但 chunks 只有 2 個 → 整 tag 降級為純文字、citations 不含
6. test_invalid_sentence_id_skipped — `c="0" s="1,99"` 且 chunk0 只有 2 句 (sids 0,1) → citation 仍生成，sentence_ids=[1] (99 被丟棄)
7. test_all_invalid_sentences_falls_back — `c="0" s="50,99"` chunk0 只有 2 句 → 整 tag 降級
8. test_no_tags — raw="just plain text" → clean_answer 不變、citations==[]
9. test_multiple_tags_numbering — 連續 3 個合法 tag → ref_num 1,2,3；clean_answer 含 "[1]","[2]","[3]"
10. test_clean_answer_no_tag_substring — 任意輸入 → "<CIT" 與 "</CIT>" 不出現在 clean_answer
11. test_citation_includes_source_path_and_page — chunk0.source_path="/x/foo.pdf" + sentence0.page=5 → citation.source_path == "/x/foo.pdf"、citation.page == 5
12. test_sentence_text_joins_referenced — `s="0,1"` chunk 有 sentences ["A.","B."] → citation.sentence_text == "A. B."
13. test_char_offsets_min_max — `s="0,2"` 對應 sentences 的 char_start/end → citation.char_start == min, char_end == max
14. test_pure_function — 同樣輸入呼叫兩次回相同結果
15. test_reverse_range_normalized — `s="5-3"` 被視為 `[3,4,5]`，不爆但發 warning
16. test_malformed_s_attribute_falls_back — `s="abc"` → tag 降級

## 不在範圍內
- 跨 LLM 回應的 streaming 處理
- 自動重試（讓 LLM 修正非法 citation）
- 信心度評分
