# Spec 102 — Multi-format Loaders

> 對應重建計畫 §「Spec 102 — Multi-format Loaders」、§「Phase 2 — 功能並行」。
> 上游：Spec 100（提供 `src/loaders/__init__.py` dispatcher + metadata 慣例）。
> 下游：Spec 105（UI file_uploader 開放四種新 ext）。

---

## 1. Context

Tier 1 的 `load_file` 只接 `.pdf` / `.md` / `.txt`（`rag.py` L75-90）。內部 demo 蒐集到的文件實際分布有大量：

1. **DOCX**：行政部門法規、會議紀要、年度策略文件。直接餵 PDF 化會丟掉 heading 結構，使用者問「2024 信用卡業務」這類聚焦章節的問題時，retrieve 命中率明顯下降。
2. **XLSX**：KPI 表、客戶名單、進銷貨明細。Tier 1 完全不支援，使用者手動轉成 CSV/MD 後語意流失（行列關係沒了）。
3. **HTML**：對外新聞稿、員工內部公告、爬蟲匯入的網頁存檔。Tier 1 不支援；若改餵成 .txt 會帶大量 `<nav>` / `<footer>` 噪音污染 retrieve。

本 spec 在 `src/loaders/` 加 3 個 loader，**重用** Tier 1 已驗證的 chunking + ingest + retrieval 全鏈路，只擴 dispatcher 與 metadata 欄位約定。**不**加 OCR、**不**做 URL 抓取、**不**支援 `.pptx`。

---

## 2. Scope

### In scope

- `src/loaders/docx_loader.py`：用 `python-docx` 讀 paragraphs + heading styles
- `src/loaders/xlsx_loader.py`：自寫 `openpyxl` 迴圈，每 sheet 每 50 row 切成一個 `Document`
- `src/loaders/html_loader.py`：用 `bs4` 移除噪音標籤後抽 main / article / body
- 擴充 `src/loaders/__init__.py` 的 `load_file` dispatcher：副檔名分流 + 不支援副檔名清晰 `ValueError`
- 新依賴鎖在 `pyproject.toml`：`python-docx>=1.1`、`openpyxl>=3.1`、`beautifulsoup4>=4.12`、`lxml>=5.0`
- `contracts/loaded_doc_metadata_schema.py` 規範 metadata 欄位
- 3 個 tiny fixtures：`tests/fixtures/docs/tiny.{docx,xlsx,html}`
- 3 個 unit test：`test_loaders_docx.py` / `test_loaders_xlsx.py` / `test_loaders_html.py`

### Out of scope

- **OCR / image-only PDF / 圖片內文字**（**第 1 次重複提醒**）
- **URL 抓取**（**第 1 次重複提醒**）：HTML loader 只接已下載到本地的檔案
- **`.pptx`**（**第 1 次重複提醒**）
- DOCX 圖片、表格、嵌入物件（只取 paragraphs + heading styles）
- XLSX 公式內容（取 `cell.value`，已是計算後的值；formula 字串不額外處理）
- XLSX 合併儲存格特殊處理（讀首格 value，其餘為 None，照原樣輸出）
- HTML CSS / JavaScript 執行（純靜態 parse）
- HTML iframe 內文（已被 noisy tag 過濾名單包含）
- HTML `<table>` 結構化抽取（直接取 text content）
- 加密 / 受密碼保護的檔案（loader 直接 raise）
- 變動 Tier 1 `.pdf` / `.md` / `.txt` loader 行為（Spec 100 已 hash-equal 鎖定）
- chunking / vectorstore / retrieve 階段任何變動

---

## 3. 核心設計決策

### 3.1 沿用 Tier 1 chunk_id 規則，XLSX 用 `source = "{filename}#{sheet_name}"` 隔離

**決定**：XLSX 多 sheet 不在 chunking 階段做特例；改在 loader 階段把 `source` 設成 `"foo.xlsx#sheet1"`、`"foo.xlsx#sheet2"`，由 `chunking.py` 既有 `doc_id = md5(source)[:10]` 自然產生不同 `doc_id`。

**為何**：
- Tier 1 `chunk_id` 已驗證的「零特例」設計（rag.py L107-114）若為 XLSX 在 chunking 內加分支，會把 Spec 100 AC #2 的「`chunk_id` byte-identical」契約弄破
- 把「sheet 是獨立邏輯 doc」的決策放在 loader 層，與 Tier 1 「source 是 doc 邊界」的隱含假設一致
- list_sources 自動回 `["foo.xlsx#sheet1", "foo.xlsx#sheet2"]`，UI 顯示就帶 sheet 資訊，無需改 vectorstore

**影響**：
- UI 顯示「已入庫文件」清單會出現 `"foo.xlsx#sheet1"` 格式（Spec 105 自行決定要不要 group by `xlsx` 顯示）
- `RetrievedChunk.source` 字串包含 `#`，下游 Spec 103 持久化時直接照存即可

### 3.2 XLSX 每 50 row 預切（pre-chunking）

**決定**：每個 sheet 內每 50 row 包成一個 `Document`，**而非整個 sheet 一個大字串**；row_range 寫入 metadata。

**為何**：
- 大 KPI 表動輒 5000 row、單 cell 平均 20 字 → 整 sheet 一個 Document 會撐到 100K 字元，遠超 `chunk_size=512`，後續 RecursiveCharacterTextSplitter 切時會在不自然的位置斷（同一 row 被切兩半）
- 50 row 約 5K 字（典型 KPI 表），剛好讓 chunking 內 splitter 在自然邊界（換行）切
- row_range 寫入 metadata 讓 UI 引用顯示「第 51-100 列」

**影響**：
- 同 sheet 內多個 Document 共用 `source`（含 `#sheet_name`），`chunk_index` 在後續 chunking 階段才 0-based 連號
- 每個 Document `page_content` 是 row 用 `\n` 串接的字串，每 cell 用 `\t` 分隔（含 header row）

```python
# 偽程式
for sheet in wb.worksheets:
    rows = list(sheet.iter_rows(values_only=True))
    header = rows[0]
    for start in range(1, len(rows), 50):
        block = rows[start:start + 50]
        text = "\t".join(str(c or "") for c in header) + "\n"
        text += "\n".join("\t".join(str(c or "") for c in r) for r in block)
        yield Document(
            page_content=text,
            metadata={
                "source": f"{filename}#{sheet.title}",
                "page": 0,
                "sheet": sheet.title,
                "row_range": f"{start}-{min(start + 49, len(rows) - 1)}",
            },
        )
```

### 3.3 DOCX 用 heading style 追蹤 section

**決定**：遍歷 `doc.paragraphs`，維護「最近一層 heading 1/2/3」狀態變數 `current_section`；每個非 heading 段落產出一個 `Document`，metadata 填當前 `section`。

**為何**：
- `python-docx` 的 `paragraph.style.name` 可分辨 `Heading 1` / `Heading 2` / `Heading 3` / `Normal` 等
- Spec 105 渲染 citation 時若 metadata 有 section，可顯示「來源：annual_report.docx · 信用卡業務」，比只顯示檔名資訊量大
- 不是每個 DOCX 都有 heading，缺時 `section = None`，schema 已允許

**影響**：
- 沒 heading 的段落 `section` 為 None（schema 已標 default=None）
- 多層 heading 取最深一層（h3 比 h1 優先）
- 空段落跳過

### 3.4 HTML 過濾名單 + main/article 優先

**決定**：用 `bs4` parse 後，先移除以下 tag 全部子樹：`script`、`style`、`nav`、`footer`、`aside`、`header`、`iframe`、`noscript`、`form`。再依優先級取 root：

1. 若有 `<main>` → 用之
2. 若有 `<article>` → 用之
3. fallback → `<body>`

**為何**：
- nav / footer / header / aside 是 80% 網頁噪音來源
- main / article 是 HTML5 語義標籤，明確標出「正文」
- 對沒有語義標籤的舊網頁，body 仍可用，但會帶較多噪音（接受）

**影響**：
- 一份 HTML 通常產出 1 個 Document（整篇正文），由 chunking splitter 後續切；若有多個 article（如新聞列表頁）會產多個 Document，各取一個 h1-h3 作 `section`

### 3.5 dispatcher 不支援副檔名行為

**決定**：`load_file` 對未列入支援清單的副檔名 raise `ValueError`，錯誤訊息列出**全部已支援副檔名**：

```python
SUPPORTED_EXTS = (".pdf", ".md", ".txt", ".docx", ".xlsx", ".html", ".htm")

if ext not in SUPPORTED_EXTS:
    raise ValueError(
        f"Unsupported file type: {ext}. "
        f"Supported: {', '.join(SUPPORTED_EXTS)}"
    )
```

**為何**：
- Tier 1 已用 `ValueError` + 列出 `.pdf/.md/.txt`；保留同樣 error class
- Spec 105 UI 用 `st.file_uploader(type=[...])` 也用同一份 SUPPORTED_EXTS（必要時暴露為 public）

**影響**：`.htm` / `.html` 視為同型（同樣走 html_loader）。

### 3.6 依賴版本鎖定理由

| 依賴 | 最低版本 | 為何 |
|---|---|---|
| `python-docx>=1.1` | 1.1.0（2024-01）+ paragraph.style.name 穩定 API |
| `openpyxl>=3.1` | 3.1（2023）+ data_only / values_only iter API |
| `beautifulsoup4>=4.12` | 4.12（2023）+ Python 3.12 支援 |
| `lxml>=5.0` | 5.0（2024）+ Python 3.12 加速 |

無上限，pyproject 不寫 `<` 版本鎖。

---

## 4. 詳細規格

### 4.1 `load_file` dispatcher（擴充版）

| 項目 | 內容 |
|---|---|
| 模組 | `src/loaders/__init__.py` |
| 介面 | `def load_file(path: str \| Path) -> list[Document]` |
| 行為 | 按副檔名分流；不支援副檔名 raise `ValueError`（含支援清單） |
| Metadata 後處理 | 對每個 Document 補 default `source = p.name`、`page = 0`（保留 Tier 1 行為） |

支援副檔名分流表：

| 副檔名 | 處理 module |
|---|---|
| `.pdf` | `pdf_loader.py`（Tier 1） |
| `.md` / `.txt` | `text_loader.py`（Tier 1） |
| `.docx` | `docx_loader.py`（**新增**） |
| `.xlsx` | `xlsx_loader.py`（**新增**） |
| `.html` / `.htm` | `html_loader.py`（**新增**） |

### 4.2 `docx_loader.py`

| 項目 | 內容 |
|---|---|
| 介面 | `def load(path: Path) -> list[Document]` |
| 演算法 | 1. `python_docx.Document(path)`；2. 遍歷 `doc.paragraphs`，維護 `current_section` 狀態；3. heading 段落更新狀態、不產 Document；4. 非空 normal 段落 → 1 個 Document，`metadata.section = current_section` |
| Heading 判定 | `paragraph.style.name` startswith `"Heading 1"` / `"Heading 2"` / `"Heading 3"` |
| 空段落 | `paragraph.text.strip() == ""` 時跳過 |
| 加密檔 | raise `ValueError(f"Encrypted DOCX not supported: {path.name}")` |

### 4.3 `xlsx_loader.py`

| 項目 | 內容 |
|---|---|
| 介面 | `def load(path: Path) -> list[Document]` |
| 演算法 | 見 §3.2 偽程式；用 `openpyxl.load_workbook(path, data_only=True)` |
| 每 50 row 包 1 Document | 包含 header row（每個 Document 都重複 header） |
| `source` 格式 | `f"{path.name}#{sheet.title}"` |
| 空 sheet | 跳過（不產 Document） |
| 加密 / 二進位錯誤 | raise `ValueError(f"Invalid XLSX: {path.name}")` |
| 公式 cell | `data_only=True` 取計算後值；無快取值時為 None，照原樣輸出 |

### 4.4 `html_loader.py`

| 項目 | 內容 |
|---|---|
| 介面 | `def load(path: Path) -> list[Document]` |
| Parser | `BeautifulSoup(content, "lxml")` |
| 噪音名單 | `script, style, nav, footer, aside, header, iframe, noscript, form` 全部 `.decompose()` |
| Root 優先級 | `<main>` > `<article>` > `<body>` |
| 抽文字 | `root.get_text(separator="\n", strip=True)` |
| Section | root 內最近一層 `h1` / `h2` / `h3` 的 text；找不到為 None |
| 多 article | 若 root 是 body 且含多個 `<article>` → 每個 article 一個 Document（各自抽 section） |
| 編碼 | 用 UTF-8 讀，若失敗 fallback `bytes` + lxml 自偵測 |

### 4.5 `LoadedDocMetadata` 驗證的時機

Loader 內不主動呼叫 `LoadedDocMetadata.model_validate(...)`（避免效能熱點），但**單元測試必驗**：每個 loader test 結尾對所有產出 Document `metadata` 呼叫 model_validate，schema 守門。

---

## 5. 特別處理

### 5.1 XLSX `source` 含 `#` 字元 vs Chroma id

Chroma id 允許含 `#`。Tier 1 `chunk_id = f"{doc_id}:{chunk_index}"`，`doc_id` 是 md5 hex（無 `#`），所以即使 source 含 `#`，最終 chunk_id 不會與其他 id 衝突。已驗證。

### 5.2 DOCX heading 4-6 處理

只追蹤 heading 1-3，h4 以下視為 normal paragraph（不更新 section）。理由：保留語義最強的章節層級即可，過深會造成 section 噪音。

### 5.3 HTML 用 lxml 嚴格模式 vs 寬鬆模式

lxml 預設寬鬆 parse，不嚴格符合 spec 的 HTML 也能讀，與 bs4 預設組合相容。受密碼 / 防火牆攔截後拿到的錯誤頁也能 parse（但取出的內容會是錯誤頁文字，這是合理行為）。

### 5.4 大檔保險（軟提醒，不在 AC）

XLSX 超過 10 萬 row 的情況：每 50 row 一 Document 會產 2000 個 Document，後續 chunking + embedding 會跑很慢。**本 spec 不強制限制**（內部 demo 用），但 loader 內以 INFO log 警示：

```python
if total_rows > 10000:
    log.warning(f"[xlsx_loader] {path.name}#{sheet.title} has {total_rows} rows, expect slow ingest")
```

### 5.5 metadata 嚴格性 vs `extra="allow"`

`LoadedDocMetadata` 用 `extra="allow"`，因為 chunking 階段會再加 `doc_id` 與 `chunk_index`，並非本 spec 控制。**但** 本 spec 承諾填的欄位（`source` / `page` / `section?` / `sheet?` / `row_range?`）必須語意正確。

---

## 6. DTO 欄位設計總表

### LoadedDocMetadata

| 欄位 | 型別 | 必填 | 由哪個 loader 填 | 說明 |
|---|---|---|---|---|
| `source` | str | Y | 全部 | XLSX 為 `"{filename}#{sheet_name}"` |
| `page` | int (≥0) | N（default 0） | PDF 真實頁碼；其他全為 0 | |
| `section` | str \| None | N | DOCX heading 1-3、HTML 最近 h1-h3 | 其他 loader 為 None |
| `sheet` | str \| None | N | XLSX 工作表名 | 其他 loader 為 None |
| `row_range` | str \| None | N | XLSX `"{start}-{end}"` 1-based | 其他 loader 為 None |

`model_config = ConfigDict(extra="allow")`：允許 chunking 階段加 `doc_id` / `chunk_index`。

---

## 7. 與外部系統的關係

- **python-docx**：純檔案 IO，不打網路
- **openpyxl**：純檔案 IO
- **beautifulsoup4 + lxml**：純檔案 IO；不執行 JS、不抓 URL
- **無 LLM / DB 互動**：loader 階段是純解析

---

## 8. Acceptance Criteria

1. **DOCX section 抓取**：`load_file("tests/fixtures/docs/tiny.docx")`（內含 1 個 Heading 1 + 2 段 normal）回傳的 `Document` list 中，至少 1 個 `metadata["section"]` 非 None 且等於 fixture 內 heading 文字（如 `"信用卡業務"`）。
2. **XLSX 多 sheet 隔離**：`load_file("tests/fixtures/docs/tiny.xlsx")`（內含 2 sheets × 3 rows）回傳的 Document 集合中，不同 sheet 的 `metadata["source"]` 必含 `"#"` 且不相等；經 `chunking.py` 處理後不同 sheet 的 `doc_id` 不相等。
3. **HTML 噪音過濾**：`load_file("tests/fixtures/docs/tiny.html")`（內含 `<nav>` `<footer>` `<script>` 區塊與 `<main>` 正文）回傳的 Document 中，`page_content` **不含** `<nav>` `<footer>` `<script>` 內任何字串。
4. **不支援副檔名 raise**：`load_file("foo.pptx")` raise `ValueError`，錯誤訊息含 `".docx"` `".xlsx"` `".html"` 至少三者其一（驗 dispatcher 列出支援副檔名）。
5. **Tier 1 三格式 hash-equal**：對 `tests/fixtures/docs/tiny.{pdf,md,txt}` 三檔，本 spec migration 後 `load_file(p)` 回傳的 `[d.page_content for d in docs]` 與 Spec 100 結束時的 byte-identical（用 md5 比對）。
6. **Metadata schema 守門**：對 `.docx` / `.xlsx` / `.html` 任一 fixture 載入後，每個 `Document.metadata` 呼叫 `LoadedDocMetadata.model_validate(d.metadata)` 不 raise。
7. **XLSX 每 50 row 切**：fixture 改為 1 sheet × 120 rows 時，產出的 Document 數 == 3（rows 1-50, 51-100, 101-120），且每個 `metadata["row_range"]` 字串正確（`"1-50"` / `"51-100"` / `"101-120"`）。
8. **DOCX 加密拒絕**：對加密 docx fixture（用 conftest 動態產一個），`load_file(...)` raise `ValueError` 含 `"Encrypted"`。
9. **HTML `<main>` 優先級**：fixture 同時含 `<main>` 與 `<body>` 文字時，`page_content` 只含 `<main>` 內字串，不含 `<main>` 外（但仍在 body 內）的文字。
10. **依賴版本鎖**：`pyproject.toml` 內 `python-docx`、`openpyxl`、`beautifulsoup4`、`lxml` 都標 `>=` 版本（依 §3.6）。
11. **每個 loader test 全綠**：`pytest tests/unit/test_loaders_docx.py tests/unit/test_loaders_xlsx.py tests/unit/test_loaders_html.py -q` 退出碼 0。

---

## 9. 與其他 spec 的介面

| 對象 spec | 本 spec 暴露 / 消費什麼 | 對方怎麼用 |
|---|---|---|
| **Spec 100 Migration** | **消費** `src/loaders/__init__.py` dispatcher 結構、`Document` metadata 慣例（`source` / `page` / `doc_id` / `chunk_index`） | dispatcher 既有 `.pdf` / `.md` / `.txt` 分支不可改；只擴充新副檔名分支 |
| **Spec 100 Migration** | **暴露** `LoadedDocMetadata` schema | Spec 100 的 `chunking.py` 不需改：metadata 多欄位以 `extra="allow"` 自然透傳 |
| **Spec 105 UI Integration** | **暴露** `SUPPORTED_EXTS` 常數（從 `src/loaders/__init__.py` import） | `st.file_uploader(type=[...])` 直接用此常數，避免 hard-code 漂移 |
| **Spec 103 Chat History** | **暴露** `RetrievedChunk.source`（含 `"#sheet"`）格式 | 持久化 `StoredCitation` 時照存 `source` 字串，不解析 |
| **Spec 104 Quality Eval** | 無直接介面 | eval 階段只看 `RetrievedChunk.text`，不關心 metadata |

---

## 10. Out of scope（再次強調）

- **OCR / image-only PDF**（**第 2 次重複提醒**）
- **URL 抓取**（**第 2 次重複提醒**）
- **`.pptx`**（**第 2 次重複提醒**）
- DOCX 圖片 / 表格 / 嵌入物件
- XLSX 公式字串、合併儲存格特殊處理
- HTML JavaScript 執行、CSS 渲染、iframe 內文
- HTML `<table>` 結構化抽取（純文字 fallback）
- 加密 / 受密碼保護檔案（直接 raise）
- 改 Tier 1 PDF / MD / TXT loader 行為（Spec 100 hash-equal 鎖定）
- chunking 階段任何變動
- 大檔分頁 streaming（內部 demo 不需）

---

## 11. 參考

- 重建計畫：`~/.claude/plans/rag-citation-mvp-rag-citation-memoized-locket.md` §「Spec 102 — Multi-format Loaders」
- 上游：[Spec 100](../100-migration-foundation/spec.md)
- 下游：[Spec 105](../105-ui-integration/spec.md)
- SDD 規範：[`specs/CLAUDE.md`](../CLAUDE.md)
