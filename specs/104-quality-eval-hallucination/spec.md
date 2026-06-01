# Spec 104 — Quality Evaluation & Hallucination Detection

> 對應重建計畫 §「Spec 104 — Quality Evaluation & Hallucination Detection」、§「Phase 2 — 功能並行」。
> 上游：Spec 100（`RetrievedChunk` / `RagAnswer` / `renumber_and_filter`）。
> 下游：Spec 105（UI 在 citation expander 下方加 QualityReport 區塊）。

---

## 1. Context

Tier 1 的 inline `[n]` citation 雖然強制 LLM 標來源，但無法防：

1. **句子內無 [n] marker 卻在答；或 [n] 對應的 chunk 與該句內容無關**：renumber 階段不檢查語意，只看 marker 編號是否在 retrieve 範圍內。
2. **實體編造**：LLM 可能在被 source 支持的句子裡偷帶數字（「2024 年信用卡發卡 300 萬張」是真的，但接著「營收 100 億」是編造，兩者共用一個 [1]）。Tier 1 的 [1] 仍是 valid，使用者無從察覺。
3. **使用者沒看出 hallucination 風險**：UI 直接顯示答案，沒有「品質指示燈」。

本 spec 加 post-hoc 評估：對 `RagAnswer.answer` + `RagAnswer.retrieved` 做純規則式分析，吐 `QualityReport` 含 `quality_score`（句級 supported 比例）與 `unsupported_entities` 紅標。**零 LLM 呼叫、零 NER、零新依賴、零隨機**、< 500ms。**只標記不修改**答案。

---

## 2. Scope

### In scope

- `src/eval/support.py`：句切分 + 句級 support 判定（3-gram character overlap）
- `src/eval/entities.py`：純 regex 偵測實體 + cited chunks substring 檢查
- `src/eval/report.py`：`evaluate(answer: str, retrieved: list[RetrievedChunk]) -> QualityReport`
- `src/eval/__init__.py`：re-export `evaluate` 與 contracts model
- `tests/unit/test_eval_support.py`、`test_eval_entities.py`
- snapshot fixtures：`tests/fixtures/snapshots/eval_*.json`（用於 regression）
- Pydantic schema + 2 fixtures

### Out of scope

- **重寫答案 / 自動修正**（**第 1 次重複提醒**）：只標記、不改 `answer` 字串
- **LLM-as-judge**（**第 1 次重複提醒**）：不打 LLM
- **NER 套件（spaCy / hanlp / ckip）**（**第 1 次重複提醒**）：純 regex
- jieba / 中文分詞依賴
- rag-citation 套件 / 任何 GPU 相依
- 持久化 QualityReport 進 SQLite（v3 backlog）
- 文件去重 / contradiction detection（v3 backlog）
- 多語言（v2 只處理中文 + 英文混合）
- 對檢索之外的事實做查證（如外部 API 驗證）
- UI 渲染邏輯（Spec 105 負責）

---

## 3. 核心設計決策

### 3.1 純規則 + 3-gram overlap，不打 LLM

**決定**：句級 support 用 3-gram character overlap 比對句子 vs cited chunks。

**為何**（已評估三條：A / B / C）：
- **A. rag-citation 套件**：大量依賴 + GPU + 英文導向 → ❌ 對內部 demo 太重
- **B. 自寫 token overlap + regex**（**本 spec 採此**）：零依賴 / deterministic / < 500ms
- **C. LLM-as-judge**：latency × 2 + 非 deterministic + 循環依賴自己模型 → ❌

3-gram character overlap 在中文場景特別合適：
- 中文無空格分詞，char-level n-gram 比 token-level 更穩
- 3-gram 比 2-gram 更精準（少數高頻 bigram 如「業務」「金融」會稀釋分數）
- 比 4-gram 更寬容（短句 / 改寫過的句子仍能命中）

**影響**：閾值 0.15 是經驗值（spec author 預設，後續若效果不佳由 Lead 仲裁調整）。

### 3.2 句切分演算法

**決定**：

```python
import re

_CN_TERMINATORS = "。！？"
_SENT_SPLIT_RE = re.compile(rf"(?<=[{_CN_TERMINATORS}])|\n+|(?<=[.!?])\s+")

def split_sentences(text: str) -> list[str]:
    """中英混合句切分。
    - 中文：[。！？] 終止符後切
    - 英文：[.!?] 後接空白才切（保留 'U.S.A.' 之類縮寫）
    - 換行：強制切
    """
    sents = [s.strip() for s in _SENT_SPLIT_RE.split(text) if s and s.strip()]
    return sents
```

**為何**：
- 中文用 lookbehind 確保終止符本身留在前一句
- 英文 `(?<=[.!?])\s+` 要求終止符後有空白，避免縮寫切錯
- `\n+` 處理 markdown 段落

**影響**：
- 純空白句、純標點句被自然濾掉（`s.strip()` 後為空）
- 句子可能含多個 `[n]` markers（正常）
- 句子內可能含換行（如 list item）→ 不切，視為一句

### 3.3 實體偵測：純 regex

**決定**：用以下 regex 偵測，**不**做 NER：

| Pattern | 對應 EntityKind | 範例 match |
|---|---|---|
| `\d+(?:\.\d+)?\s*(?:億|萬|百萬|千|%|‰)` | `NUM` | `100 億`、`50%`、`3.5 萬` |
| `\d{4}年` | `DATE` | `2024 年` |
| `\d{4}-\d{1,2}-\d{1,2}` | `DATE` | `2024-01-15` |
| `\d{1,2}月\d{1,2}日` | `DATE` | `1 月 15 日` |
| `Q[1-4]\s?\d{4}` / `\d{4}\s?Q[1-4]` | `DATE` | `Q4 2024` / `2024 Q4` |

PER / ORG / LOC 在 v2 **不**偵測（保留 enum 給 v3）。

**為何**：
- 數字與日期是最常見、最容易被 LLM 編造、且最容易用 regex 抓的實體類型
- 人名 / 公司名 / 地名需 NER 才能可靠識別，違反「零新依賴」原則
- regex 對中英文都通用

**影響**：v2 的「unsupported_entities」主要會是 NUM / DATE；人名類 hallucination 須靠句級 support 抓（overlap 低 → 整句被標）。

### 3.4 實體 substring 檢查

**決定**：對每個偵測到的實體，做以下檢查：

```python
def is_entity_supported(entity: str, retrieved: list[RetrievedChunk]) -> bool:
    """實體只要在任一 retrieved chunk text 內為 substring 即視為 supported。"""
    return any(entity in c.text for c in retrieved)
```

**為何**：
- 用 `retrieved` 而非 `citations`：使用者問題經 retrieve 後拿到 top_k chunks，這是 LLM 可看見的資訊範圍。即使 LLM 沒在句尾標 [n]（沒被 citations 包含），只要 retrieved 內有就視為「有 source 可佐證」
- substring 是最寬鬆的檢查；若答案內寫「100 億」、chunk 寫「100 億元」也能命中
- 規則式可解釋：使用者點開 EntityFlag 可知道為何被 flag

**影響**：
- 數字格式略有差異會 miss（如「100億」vs「100 億」）→ entity regex 已加 `\s*` 容忍
- 答案內每個實體只 flag 一次（用 set 去重）

### 3.5 quality_score 計算

**決定**：

```python
total = len(sentence_supports)
supported = sum(s.supported for s in sentence_supports)
quality_score = supported / total if total > 0 else 1.0
```

無句子時為 1.0（避免除 0、「無答案沒問題」是合理 default）。

### 3.6 句中無 [n] marker 的處理

**決定**：若句中無任何 `[n]` marker：
- `supported = False`
- `best_match_chunk_id = None`
- `overlap_score = 0.0`

**為何**：
- Tier 1 系統 prompt 強制要求「每段論述結尾必須標註來源編號」；無 marker 表示 LLM 違反 prompt → 視為不可信
- 對「依現有資料無法回答」這種 boilerplate 句子是誤判，但這類句子應該由 caller 在 evaluate 前判斷是否跳過（**本 spec 不做特例**）

**影響**：實作者必須注意「`evaluate` 是純函式，不感知答案是否為 empty-knowledge fallback」。caller（Spec 105 UI）可選擇在 `RagAnswer.retrieved == []` 時不顯示 QualityReport。

### 3.7 性能與 deterministic 保證

**決定**：
- 不打網路、不打 LLM
- 不用 `random` / `time.time()`
- 不依賴 Python dict / set 序遍歷（用 list 保序）

效能目標：**5 chunks × 答案 300 字 → < 500ms**。實測上應遠快於此（純 regex + 字串 in 檢查），AC 設 500ms 是上限保險。

---

## 4. 詳細規格

### 4.1 module 介面

| 模組 | 暴露 | 行為 |
|---|---|---|
| `src/eval/support.py` | `split_sentences(text) -> list[str]`、`evaluate_support(sentences, retrieved) -> list[SentenceSupport]` | 句切分 + 句級 overlap |
| `src/eval/entities.py` | `detect_entities(text) -> list[tuple[str, EntityKind]]`、`evaluate_entities(answer, retrieved) -> list[EntityFlag]` | 純 regex 偵測 + substring 檢查 |
| `src/eval/report.py` | `evaluate(answer: str, retrieved: list[RetrievedChunk]) -> QualityReport` | top-level，組合上兩者 |
| `src/eval/__init__.py` | re-export `evaluate` + schema | 給 caller 用 |

### 4.2 `evaluate` 主流程

```python
def evaluate(answer: str, retrieved: list[RetrievedChunk]) -> QualityReport:
    sentences = split_sentences(answer)
    supports = evaluate_support(sentences, retrieved)
    entity_flags = evaluate_entities(answer, retrieved)
    total = len(supports)
    score = sum(s.supported for s in supports) / total if total > 0 else 1.0
    return QualityReport(
        quality_score=score,
        sentence_supports=supports,
        unsupported_entities=entity_flags,
    )
```

### 4.3 3-gram overlap 計算

```python
def char_3gram_set(text: str) -> set[str]:
    """純字元 3-gram；忽略空白與標點？不忽略（保留原文資訊量）。"""
    return {text[i:i+3] for i in range(len(text) - 2)} if len(text) >= 3 else {text}

def overlap_score(sent: str, chunk_text: str) -> float:
    s, c = char_3gram_set(sent), char_3gram_set(chunk_text)
    if not s:
        return 0.0
    return len(s & c) / len(s)  # 句子在 chunk 中的覆蓋率
```

每句對所有 cited chunks 算 overlap，取最高分；最高分 < 0.15 視為 unsupported。

### 4.4 句級 support 判定流程

```python
def evaluate_support(sentences, retrieved):
    results = []
    chunk_by_n = {c.n: c for c in retrieved}
    for sent in sentences:
        cite_ns = [int(m.group(1)) for m in _CITE_RE.finditer(sent)]
        cited_chunks = [chunk_by_n[n] for n in cite_ns if n in chunk_by_n]
        if not cited_chunks:
            results.append(SentenceSupport(
                sentence=sent, supported=False,
                best_match_chunk_id=None, overlap_score=0.0,
            ))
            continue
        best = max(
            ((c, overlap_score(sent, c.text)) for c in cited_chunks),
            key=lambda x: x[1],
        )
        chunk, score = best
        results.append(SentenceSupport(
            sentence=sent,
            supported=score >= 0.15,
            best_match_chunk_id=chunk.chunk_id if score >= 0.15 else None,
            overlap_score=round(score, 4),
        ))
    return results
```

### 4.5 實體偵測流程

```python
_ENTITY_PATTERNS = [
    (re.compile(r"\d+(?:\.\d+)?\s*(?:億|萬|百萬|千|%|‰)"), EntityKind.NUM),
    (re.compile(r"\d{4}\s*年"), EntityKind.DATE),
    (re.compile(r"\d{4}-\d{1,2}-\d{1,2}"), EntityKind.DATE),
    (re.compile(r"\d{1,2}\s*月\s*\d{1,2}\s*日"), EntityKind.DATE),
    (re.compile(r"Q[1-4]\s?\d{4}|\d{4}\s?Q[1-4]"), EntityKind.DATE),
]

def detect_entities(text):
    seen: set[str] = set()
    out: list[tuple[str, EntityKind]] = []
    for pat, kind in _ENTITY_PATTERNS:
        for m in pat.finditer(text):
            key = m.group(0).strip()
            if key not in seen:
                seen.add(key)
                out.append((key, kind))
    return out

def evaluate_entities(answer, retrieved):
    flags: list[EntityFlag] = []
    for entity, kind in detect_entities(answer):
        if not any(entity in c.text for c in retrieved):
            flags.append(EntityFlag(
                entity=entity, kind=kind,
                reason="not found in any cited chunk text",
            ))
    return flags
```

### 4.6 閾值常數

| 常數 | 值 | 設定位置 |
|---|---|---|
| `SUPPORT_OVERLAP_THRESHOLD` | 0.15 | `src/eval/support.py` module top |
| `NGRAM_SIZE` | 3 | `src/eval/support.py` module top |

未來調整由 Lead 仲裁；不暴露為 Settings 欄位（保持 deterministic）。

---

## 5. 特別處理

### 5.1 答案內無 [n] marker 整段

句切分後每句都會跑 evaluate_support；無 marker 即 `supported=False`、`overlap_score=0.0`。例如「依現有資料無法回答」這種句子會被標 unsupported，但這是合理（caller UI 可選擇不顯示 QualityReport when `retrieved == []`）。

### 5.2 編造 [n] 不再處理

Tier 1 `renumber_and_filter` 已把編造編號 marker 從答案文字刪除。因此 evaluate 收到的 answer 中**不應**有不在 `retrieved.n` 範圍內的 marker。本 spec 仍 defensive：

```python
cited_chunks = [chunk_by_n[n] for n in cite_ns if n in chunk_by_n]
```

過濾掉萬一漏網的 marker（不 raise）。

### 5.3 中文標點 vs 英文標點混用

句切分對「，」（中文逗號）不切（不是句末）；對「,」也不切。空格不切。連續換行 `\n\n` 切。

### 5.4 短句（< 3 字元）的 overlap

句子長度 < 3 字元時 `char_3gram_set` fallback 回 `{text}`（整句作單一 token），與 chunk 比對自然得 0/1 二元結果。短句很罕見且通常不重要。

### 5.5 中英文混合句

實體 regex 對中英文都不挑（用 `\d` 與 unicode literal「年」「億」），混合句正常工作。

### 5.6 evaluate 順序保證

`sentence_supports` 的順序與答案中句子出現順序一致（split_sentences 是順序的）。`unsupported_entities` 的順序由 `_ENTITY_PATTERNS` 順序決定（NUM 先、DATE 後），同型內依答案出現順序。

### 5.7 不修改答案

`evaluate` 是純函式，**不**回傳改寫後的 answer。Caller 如要 highlight unsupported entity，要在 UI 層自己 wrap 紅色 span（Spec 105 負責）。

---

## 6. DTO 欄位設計總表

### QualityReport

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `quality_score` | float (0..1) | Y | supported 句子比例 |
| `sentence_supports` | list[SentenceSupport] | N（default []） | 順序與答案內句子順序一致 |
| `unsupported_entities` | list[EntityFlag] | N（default []） | 未在 retrieved 找到的實體 |

### SentenceSupport

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `sentence` | str | Y | 原句字串（含 [n]） |
| `supported` | bool | Y | overlap ≥ 0.15 |
| `best_match_chunk_id` | str \| None | N | supported=True 時填；其他為 None |
| `overlap_score` | float (0..1) | Y | 3-gram overlap |

### EntityFlag

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `entity` | str | Y | regex match 字串 |
| `kind` | EntityKind | Y | NUM / DATE / MISC...（v2 只填 NUM/DATE） |
| `reason` | str | Y | 為何被 flag |

### EntityKind（StrEnum）

| 值 | v2 偵測 | 用途 |
|---|---|---|
| `per` | ❌ | 人名（v3） |
| `org` | ❌ | 組織（v3） |
| `loc` | ❌ | 地名（v3） |
| `num` | ✅ | 數值 + 量詞 |
| `date` | ✅ | 日期 |
| `misc` | ✅（fallback） | 其他 |

---

## 7. 與外部系統的關係

- **無外部系統**：純 in-process Python regex + 字串比對
- **不打 LLM、不讀 DB、不讀檔**
- 純函式 → 易測、易快取（雖然 v2 不做快取，未來易加）

---

## 8. Acceptance Criteria

1. **句級 supported 判定（正例）**：給 fixture 句子 `"統一企業 1967 年成立 [1]。"` + retrieved 含 `RetrievedChunk(n=1, text="統一企業在 1967 年於台南創立，創辦人為高清愿。", chunk_id="abc:0", ...)`，呼叫 `evaluate(answer, retrieved)` 必回 `quality_score == 1.0`、`sentence_supports[0].supported == True`、`sentence_supports[0].best_match_chunk_id == "abc:0"`、`unsupported_entities == []`。
2. **實體 hallucination 偵測（反例）**：答案 `"台新銀行 2024 年信用卡發卡量 300 萬張 [1]。同年營收達 100 億元 [1]。"`，cited chunk 內含 `"300 萬張"` 但不含 `"100 億"`，呼叫 `evaluate` 必回 `unsupported_entities` 含 `EntityFlag(entity="100 億", kind=EntityKind.NUM, ...)`。
3. **quality_score 為 supported 句比例**：建構 fixture：4 句答案，前 2 句 supported、後 2 句 unsupported（透過控制 overlap），`evaluate` 回 `quality_score == 0.5`。
4. **Deterministic**：對同一 input 連跑 5 次 `evaluate`，每次回的 `QualityReport.model_dump()` 必完全相等（含浮點數）。
5. **效能上限**：用 5 個 chunks（每 500 字）+ 答案 300 字（含 4 句）連跑 100 次 `evaluate`，總時間 < 50 秒（平均 < 500ms / call）。
6. **無 [n] marker 整段**：答案 `"依現有資料無法回答。"`，呼叫 `evaluate(answer, [])` 必回 `quality_score == 0.0`、`sentence_supports[0].supported == False`、`unsupported_entities == []`。
7. **空答案**：`evaluate("", retrieved)` 回 `quality_score == 1.0`、`sentence_supports == []`、`unsupported_entities == []`。
8. **編造 [n] 不 raise**：若答案內出現 `[99]`（不在 retrieved.n 範圍），`evaluate` 不 raise；該句視為「無有效 marker」即 unsupported（與 §3.6 一致）。
9. **Schema 鎖死**：對 fixtures 兩個 JSON（supported / unsupported example）執行 `QualityReport.model_validate(...)` 不 raise。
10. **零外部依賴**：執行 `python -c "import src.eval.report; import sys; [print(m) for m in sys.modules if 'eval' in m]"` 後，import 過的 modules 不含 `jieba` / `spacy` / `hanlp` / `langchain_*`（純 stdlib + 本專案）。
11. **Pure 不修改答案**：`evaluate(answer, retrieved).model_dump()` 後，answer 字串本身不被改動（caller 持有的 answer 變數仍為原值）。

---

## 9. 與其他 spec 的介面

| 對象 spec | 本 spec 暴露 / 消費什麼 | 對方怎麼用 |
|---|---|---|
| **Spec 100 Migration** | **消費** `RetrievedChunk`（n / chunk_id / text）、`RagAnswer`（answer / retrieved） | Spec 100 不需改；eval 是純讀 |
| **Spec 100 Migration** | **消費** `_CITE_RE`（`re.compile(r"\[(\d+)\]")`） | 可自己定一份 module 內常數，無需 import；保持鬆耦合 |
| **Spec 102 Loaders** | 無直接介面 | eval 只看 `RetrievedChunk.text`，不在乎 source 是否含 `#sheet` |
| **Spec 103 History** | 無直接介面 | v2 不持久化 QualityReport（v3 backlog） |
| **Spec 105 UI Integration** | **暴露** `evaluate(answer, retrieved) -> QualityReport`、`QualityReport` / `SentenceSupport` / `EntityFlag` schema | UI 在 `query()` 完後呼叫 `evaluate(ans.answer, ans.retrieved)`，渲染 quality_score + 紅標 unsupported_entities |

---

## 10. Out of scope（再次強調）

- **重寫 / 修正答案**（**第 2 次重複提醒**）：只標記、不改字串
- **LLM-as-judge**（**第 2 次重複提醒**）：永遠不打 LLM
- **NER 套件**（**第 2 次重複提醒**）：不引入 jieba / spacy / hanlp / ckip
- **持久化 QualityReport**：v3 backlog
- 文件對立 / contradiction detection
- 多語言（v2 限中英）
- 對檢索外的事實做查證
- UI 渲染邏輯
- 調整 chunk_size / top_k 來改善 quality（屬 Spec 100 範圍）
- 串接 quality_score 進 retrieval re-ranking（v3 backlog）

---

## 11. 參考

- 重建計畫：`~/.claude/plans/rag-citation-mvp-rag-citation-memoized-locket.md` §「Spec 104 — Quality Evaluation & Hallucination Detection」
- 上游：[Spec 100](../100-migration-foundation/spec.md)
- 下游：[Spec 105](../105-ui-integration/spec.md)
- SDD 規範：[`specs/CLAUDE.md`](../CLAUDE.md)
- 評選依據（A/B/C 三條方案）：重建計畫 §「方案選型」
