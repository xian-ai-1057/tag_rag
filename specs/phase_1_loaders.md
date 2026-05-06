# Phase 1 Spec: Loaders

## 目的
把多種文件格式統一成 `Document` 物件，**保留必要的位置資訊**（特別是 PDF 的頁碼），讓後續句子切分器能算出 char offset 並對應頁碼。

## 公開介面

```python
# src/loaders.py
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class PageSpan:
    page_num: int        # 1-indexed
    char_start: int      # inclusive, in Document.text
    char_end: int        # exclusive

@dataclass(frozen=True)
class Document:
    doc_id: str          # 取檔名 stem，例如 "annual_report"
    source_path: str     # 絕對路徑字串
    text: str            # 抽取出來的純文字（已正規化換行）
    pages: list[PageSpan] | None  # 只有 PDF 才有；其他格式為 None

class UnsupportedFormatError(ValueError):
    pass

def load_document(path: str | Path) -> Document: ...
```

## 行為規範

### 通用
- `path` 不存在 → `FileNotFoundError`
- 副檔名不支援 → `UnsupportedFormatError`
- 空檔 → 回傳 `Document(text="", pages=...)` 並用 `warnings.warn(...)` 警告
- 換行統一：`\r\n` 與 `\r` 一律轉為 `\n`
- `doc_id` = `Path(path).stem`
- `source_path` = `str(Path(path).resolve())`

### `.txt` / `.md`
- UTF-8 讀取，失敗 fallback `utf-8-sig`，再失敗 raise `UnicodeDecodeError`
- `text` 為原始全文（換行正規化後）
- `pages = None`

### `.pdf`（用 `pypdf`）
- 逐頁抽 `page.extract_text()`，串接時頁與頁之間補 `\n\n`
- `pages` 紀錄每頁在 `text` 中的 `[char_start, char_end)` 範圍
- 不變式：`for span in pages: text[span.char_start:span.char_end]` 等於該頁的文字（外加分隔符）
- 沒有文字層的 PDF（每頁都抽出空字串） → 仍回傳，但發 warning「PDF 無可抽取文字，可能是掃描檔」

### `.html` / `.htm`（用 `bs4`）
- 解析後刪除 `<script>` 與 `<style>` 內容
- 用 `soup.get_text(separator="\n")`，再做兩階段清洗：
  - 連續 3+ 空白行壓成 2
  - 行首尾空白 strip
- `pages = None`

## 不變式
- 對 PDF：
  ```
  pages[0].char_start == 0
  pages[i].char_end <= pages[i+1].char_start
  pages[-1].char_end <= len(text)
  ```
- 任何成功 load 後，`Document.text` 都是 `str`，不會是 `None`

## 錯誤處理
| 情境 | 行為 |
|---|---|
| 檔案不存在 | `FileNotFoundError` |
| 不支援副檔名 | `UnsupportedFormatError` |
| PDF 損毀（pypdf 拋例外） | 包成 `RuntimeError("Failed to read PDF: ...")` |
| 空檔 | 正常回傳空 Document + warning |
| Encoding 錯誤 | 嘗試 utf-8 → utf-8-sig → 拋 `UnicodeDecodeError` |

## 驗收標準
1. `tests/test_loaders.py` 全綠
2. 對每種支援格式都有 fixture
3. PDF 多頁的 `pages` 欄位通過 char offset 不變式
4. HTML 解析後不含 `<script>` / `<style>` 內容
5. 公開符號：`Document`、`PageSpan`、`load_document`、`UnsupportedFormatError`

## 不在範圍內
- Word / PPT 直讀（使用者外部轉 txt 再進來）
- OCR
- 多檔批次處理（呼叫端用 list comprehension 即可）
- 表格結構保留（純文字即可）
