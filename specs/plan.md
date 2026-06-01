# Tag RAG — Project Plan (Specs 精煉版)

> 完整計畫見 `~/.claude/plans/rag-citation-mvp-rag-citation-memoized-locket.md`。
> 本檔是給 teammate 看的精簡版。

## 目標

從已 validated 的 Tier 1 demo（`rag.py` + `app.py`）走向 SDD 結構化 + 3 個新功能。

## Spec 依賴圖

```
                  ┌──> Spec 102 (loaders) ──┐
Spec 100 ─────────┤                          ├──> Spec 105 (UI)
(migration)       ├──> Spec 103 (history) ───┤
                  │                          │
                  └──> Spec 104 (eval) ──────┘
```

## Spec 索引

| # | Spec | 狀態 | 描述 |
|---|------|------|------|
| 100 | [migration-foundation](100-migration-foundation/spec.md) | ✅ Done | 把 rag.py 拆成 src/<module>.py，Pydantic 化 DTO |
| 102 | [multi-format-loaders](102-multi-format-loaders/spec.md) | ✅ Done | 加 DOCX / XLSX / HTML 載入 |
| 103 | [chat-history-persistence](103-chat-history-persistence/spec.md) | ✅ Done | SQLite 對話歷史持久化 |
| 104 | [quality-eval-hallucination](104-quality-eval-hallucination/spec.md) | ✅ Done | 句級 support + entity hallucination 偵測 |
| 105 | [ui-integration](105-ui-integration/spec.md) | ✅ Done | Streamlit 整合所有上游 spec |

## Tier 1 既有行為（必須保留，禁止改動）

| 行為 | 規則 | 改動需 |
|------|------|--------|
| `chunk_id` 格式 | `f"{doc_id}:{chunk_index}"` 且 `doc_id = md5(source)[:10]` | Lead 批准 |
| Renumber 規則 | 依答案中首次出現順序重編 1..N | Lead 批准 |
| 編造編號處理 | 從答案文字中刪除（不只是過濾 citations list） | Lead 批准 |
| 雙空白壓縮 | renumber 收尾 `re.sub(r" {2,}", " ", ...)` | Lead 批准 |
| `fetch_chunks_by_ids` fallback | 查不到 → UI 用 snapshot + stale 標籤 | Lead 批准 |
| Logging | INFO=pipeline / DEBUG=full prompt / noisy=WARNING | Lead 批准 |
| Empty retrieval | 回 `"依現有資料無法回答：知識庫目前是空的..."` | Lead 批准 |

## Phase 順序

1. **Phase 0**（spec writing） → 完成所有 spec.md + contracts + fixtures
2. **Phase 1**（migration） → 拆模組，`app.py` 一行不改仍能跑
3. **Phase 2**（features，平行） → loaders + history + eval 三條獨立路線
4. **Phase 3**（integration） → UI + docs + UAT

## Lead 仲裁紀錄（Phase 0 結束時）

spec-author 提出 5 項設計歧義，Lead 裁決：

1. **`snapshot_text` truncate 單一職責**：**Store 是唯一 truncate 點**（Spec 103 §3.4 已明示）。`StoredCitation` schema 的 `max_length=1000` 是防禦守門；caller（Spec 105 UI）**不需**自行截斷，傳完整字串即可，`HistoryStore.add_message` 內 truncate 並加 `"…"`。
2. **`Message.role` 接受 str 或 StrEnum**：保持 Pydantic v2 預設寬鬆性。可寫 `MessageRole.USER` 或 `"user"` 皆可。
3. **`app.py` freeze 期**：Phase 1 結束後 → Phase 3 開始前，`app.py` **不准動**（除 Phase 1 façade 相容性所需）。Phase 2 三位 teammate 都禁碰。
4. **Entity regex 對稱性**：不加 currency unit（如「元」）進 regex；數量單位「億/萬/百萬」已鎖定數量級，currency 單位是 over-fit。
5. **XLSX header row 重複**：Phase 2 `loaders-engineer` 先按 spec §3.2 實作（每 50 row 重複 header），若 retrieval 測試顯示 header 文字主導語義 → SendMessage Lead，再決定是否改成「只首個 block 含 header」。

## 完成定義（Done）

- 所有 spec AC 全綠
- `pytest tests/unit -q` 全綠
- 端到端 UAT（10 步驟）通過
- README 更新、依賴鎖定

詳見：[agent-teams-plan.md](agent-teams-plan.md)

## 完成里程碑

### Phase 0：規格設計（Specification）

完成 5 份 spec + 4 份 Pydantic schema + 10 份 fixture golden samples

### Phase 1：模組遷移（Migration）

- `rag.py` 拆成 14 個 `src/*` 模組（config / loaders / history / eval / rag_chain / retrieval / vectorstore / ingest）
- 5 份 baseline test 驗證 Tier 1 行為不變
- Façade 相容性完全保留，`app.py` 一行未改

### Phase 2：平行特性開發（Features）

3 條平行路線，74 個 unit test：

1. **Loaders（多格式）**：PDF / DOCX / XLSX / HTML / Text，段落與結構化資料保留
2. **History（對話持久化）**：SQLite，支援新建 / 切換 / 重命名 / 刪除對話
3. **Eval（品質評估）**：句級 support 判定 + entity hallucination regex 偵測，< 500ms 確定性規則

### Phase 3：UI 整合 + 文件更新（Integration & Docs）

Tier 2 完成日期：2026-05-26

- Streamlit app 整合 loaders / history / eval 全部特性
- README 更新：新增 6 格式表、對話歷史說明、品質評估解釋
- CLAUDE.md 更新：Tier 2 標記完成、重點檔案表、程式碼風格補充
- specs/plan.md 更新：所有 spec 標記完成、里程碑記錄
