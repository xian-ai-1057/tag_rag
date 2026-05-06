# Phase 2 Spec: Sentence Splitter

## 目的
把 `Document.text` 切成有序句子陣列，**保留每句相對於原文的 character offset**，並（若是 PDF）標註句子所在頁碼。char offset 是後續 citation 反查的命脈。

## 公開介面

```python
# src/splitter.py
from __future__ import annotations
from dataclasses import dataclass

from src.loaders import Document

@dataclass(frozen=True)
class Sentence:
    sid: int             # 在整份文件中的句子序號（0-indexed），全文唯一
    text: str            # 句子文字（包含結尾標點，去除前後空白）
    char_start: int      # 在 Document.text 中的起始字元索引（0-indexed, inclusive）
    char_end: int        # exclusive
    page: int | None     # 1-indexed；非 PDF 文件為 None

def split_sentences(doc: Document) -> list[Sentence]: ...
```

## 行為規範

### 段落界線
連續 2+ 個 `\n` 視為段落分隔。段落內若仍有單個 `\n`（PDF 換行），視為句中軟斷行，不影響句子切分。

### 句子界線（regex 為主）
- **中文/日文/全形句末**：`。`、`！`、`？`、`…`、`；`（半形分號可選地放）
- **英文句末**：`.`、`!`、`?` 後跟空白與下一個字（或文末）
- **常見縮寫不切**：`Mr.`、`Mrs.`、`Ms.`、`Dr.`、`Prof.`、`Inc.`、`Ltd.`、`vs.`、`etc.`、`e.g.`、`i.e.`、`No.`、`Fig.`、`Eq.`、`et al.`
- **數字小數點不切**：`3.14`、`v1.2`
- **省略號**：英文 `...` 與中文 `…` 視為一個句末標記

### 不變式（最關鍵）
對於切出的每個 `Sentence s`：
```
doc.text[s.char_start:s.char_end] == s.text  ← 嚴格相等
```
**注意**：句子文字必須是「原文連續切片」，不可改寫、不可去頭尾空白後存（要嘛保留原樣，要嘛 `char_start/char_end` 跟著移動）。

實作建議：先用 regex 找句末位置，從位置 i 切到下一個句末位置 j，得到 raw `[i:j]`；接著去掉前導空白 ws 與尾端空白 we，最終 `char_start = i + ws`、`char_end = j - we`，`text = doc.text[char_start:char_end]`。

### Page 對應
若 `doc.pages` 非 None：句子的 `page` 取「該句 char_start 落在哪個 PageSpan 內」。如果句子跨頁（罕見），取 `char_start` 所屬頁。

### 空白與空句
- 連續多個空白行只產生段落分隔，不產生空句子
- 整份文件為空 → 回傳空 list

## 驗收標準
1. `tests/test_splitter.py` 全綠
2. **char offset 不變式**：對隨機混合中英 fixture 切出的所有句子，斷言 `doc.text[s.char_start:s.char_end] == s.text`
3. `Mr. Smith went home.` 切成 1 句而非 2 句
4. `3.14 is pi.` 切成 1 句
5. PDF 多頁文件每句都有正確 `page` 屬性
6. `sid` 從 0 連續遞增

## 不在範圍內
- 段落級切分輸出（Phase 3 chunk builder 會再用，但這階段只輸出句子）
- 跨語言詞性標注、命名實體
- 引號內句子的特殊處理（"He said. She left." 簡單從句號切就好）
