# Agent Teams Plan — Phase 配置總覽

## 原則

- 每 Phase 一 Team，做完即解散
- 每人任務數 ≤ 6
- 兩位 teammate 不可動同一檔案
- Plan Approval 強制：readonly plan → message Lead 批准 → 才實作
- LLM 呼叫測試一律 mock

## Phase 配置

### Phase 0 — Spec Writing（3 人）

| Teammate | Type | Model | 任務 |
|----------|------|-------|------|
| `navigator` | Explore | sonnet | 掃 Tier 1 程式碼，產出「既有行為清單」（已由 Lead 完成於 plan §Tier 1 Completed，本 Phase 可省） |
| `spec-author` | general-purpose | opus | 寫 5 份 spec.md + contracts schemas + golden fixtures |
| `design-reviewer` | Plan | opus | 對每份 spec readonly review，挑戰 AC 可測性 + 跨 spec 對齊 |

**範圍**：`specs/100-*/`、`specs/102-*/`、`specs/103-*/`、`specs/104-*/`、`specs/105-*/`

**Demoable**：5 spec + 所有 fixture `model_validate()` 全綠。

---

### Phase 1 — Migration（2 人）

| Teammate | Model | 可動檔案 |
|----------|-------|----------|
| `migrator` | sonnet | `src/{config,logging_setup,chunking,vectorstore,ingest,retrieval,prompts,citation,llm,rag_chain}.py`、`src/loaders/{__init__,text_loader,pdf_loader}.py`、`rag.py` → façade、`tests/unit/test_{citation,chunking}.py`、`tests/integration/test_pipeline_end_to_end.py`、`tests/fixtures/docs/tiny.{pdf,md,txt}`、`scripts/regression.sh` |
| `contracts-guardian` | sonnet | `specs/100-*/contracts/fixtures/`、`tests/unit/test_contracts_fixtures.py` |

**Demoable**：`app.py` 一行不動仍可啟動；Tier 1 4 個 case + unit-level 3 邊界全綠。

---

### Phase 2 — 功能並行（3 人，檔案完全不撞）

| Teammate | Model | 可動檔案 |
|----------|-------|----------|
| `loaders-engineer` | sonnet | `src/loaders/{docx_loader,xlsx_loader,html_loader}.py`、`src/loaders/__init__.py`、`tests/unit/test_loaders_{docx,xlsx,html}.py`、`tests/fixtures/docs/tiny.{docx,xlsx,html}` |
| `history-engineer` | sonnet | `src/history/{__init__,store,models}.py`、`tests/unit/test_history_store.py` |
| `eval-engineer` | **opus** | `src/eval/{__init__,support,entities,report}.py`、`tests/unit/test_eval_{support,entities}.py`、`tests/fixtures/snapshots/eval_*.json` |

**Demoable**：三 spec 各自 AC 5 條全綠，可獨立 `pytest tests/unit/test_{loaders_*,history_store,eval_*}` 全跑。

---

### Phase 3 — Integration & Polish（2 人）

| Teammate | Model | 可動檔案 |
|----------|-------|----------|
| `ui-integrator` | sonnet | `app.py`、`pyproject.toml`、`.env.example` |
| `doc-updater` | haiku | `README.md`、`CLAUDE.md`、`specs/plan.md` status 標記 |

**Demoable**：手動 UAT 跑 Spec 105 五條 AC 全綠。

---

## 任務數核對（每人 ≤ 6）

| Teammate | 任務數 | 範圍 |
|----------|--------|------|
| spec-author | 5 | 5 specs + contracts + fixtures（每 spec 內含寫 spec + schema + 1-2 fixtures） |
| design-reviewer | 5 | 對 5 spec readonly review |
| migrator | 6 | 拆 10 個 .py + 寫 façade + 2 unit test + 1 integration test + 3 fixture files + regression.sh |
| contracts-guardian | 2 | fixtures validate test + golden snapshot |
| loaders-engineer | 6 | 3 loaders + dispatcher + 3 tests + 4 fixtures（合併計算） |
| history-engineer | 5 | SQLite store + models + CRUD + WAL config + test |
| eval-engineer | 6 | sentence support + entity + report + 2 tests + snapshot fixtures + Pydantic schemas |
| ui-integrator | 5 | app.py rewrite + sidebar + quality panel + pyproject + .env |
| doc-updater | 3 | README + CLAUDE.md + plan status |

全部 ≤ 6 ✅

---

## Plan Approval Prompt 範本

詳見 `~/.claude/skills/sdd-agent-teams/assets/templates/plan-approval-prompt.tmpl`。

每位 teammate 啟動時 Lead 套此範本，明示：
- 你是哪個 teammate
- 可動 / 不可動檔案
- 對應 spec.md 路徑
- 上下游 contract
- 流程（plan → 等批准 → 實作 → 跑 test → SendMessage Lead）

## 解散時機

每 Phase 驗收通過後 Team 立刻解散。下 Phase 重組，**不**沿用上 Phase teammate context。
