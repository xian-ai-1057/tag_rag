# Specs Directory — Guide for Teammates

## 你在這裡時的規則

進入 `specs/` 子目錄的 teammate 會自動載入本檔。這些規則高於一切，必須遵守：

### 1. Spec 是單一事實

- `specs/<NNN>-<name>/spec.md` 描述 What / Why / AC
- 發現 spec 漏洞、矛盾、模糊不清 → **不要自行解讀**，SendMessage Lead 改 spec
- 你絕對不能修改任何 spec.md（Lead 唯一可寫）

### 2. Contracts 是介面契約

- `contracts/<name>_schema.py` 是 Pydantic v2 DTO（已被 spec-author 鎖死）
- `contracts/fixtures/*.json` 是 golden samples
- **你不能改 contracts schema**，只能新增 fixtures（且要通過 `model_validate()`）
- 任何介面變動要回報 Lead

### 3. 檔案隔離

- 你的 prompt 會明示「可動檔案」與「不可動檔案」
- 兩位 teammate 不可同改一檔案
- 超出範圍 → SendMessage Lead 重分配

### 4. By-design 不做的事

每份 spec 的 §Out of scope 都有「重複提醒 ×N」標註。LLM 容易自作主張「順便補上」這些 — **絕對不要**。

### 5. 測試規約

- LLM 呼叫一律 mock，不打真 Ollama（除非 spec 明示）
- 測試命名：`test_<feature>_<scenario>_<expected>()`
- Unit test 放 `tests/unit/`、integration 放 `tests/integration/`
- 用 `@pytest.mark.requires_ollama` 標記需要本地 Ollama 的 test

### 6. 命名規約（Python-LLM profile）

- Pydantic DTO：`<Feature>DTO`、`<Feature>Result`、`<Feature>Context`
- 列舉：`StrEnum`，命名 `<Field>Type` / `<Field>Kind`
- 列表預設值：`Field(default_factory=list)`，**不要** `default=[]`
- Optional：`str | None`，**不要** `Optional[str]`
- 嚴格 DTO：`model_config = ConfigDict(extra="forbid")`

### 7. Plan Approval 流程

當你是 readonly plan mode：

1. 讀 spec.md + contracts + 上下游既有檔案
2. 產出 `plan.md` 包含：
   - 可動檔案清單
   - 設計概念
   - 與其他 teammate 的契約
   - 風險與替代方案
   - 測試清單（具體 test function 名）
   - 與 spec 的偏離（如有，明標理由）
3. SendMessage Lead 請求批准
4. 批准後切到實作 mode，跑 unit test 全綠後 SendMessage 完成

### 8. 不要做

- 不要寫 docstring 給每個 function（只在複雜邏輯寫）
- 不要加 emoji 到 code（除非 spec 或 prompt 明示）
- 不要 over-engineer：MVP 等級的 pytest 即可，不需 100% coverage
- 不要碰 `data/`、`Archive/`、`rag.py`（除非你是 migrator）

## 目錄結構

```
specs/
├── CLAUDE.md                    ← 你正在讀
├── plan.md                      ← 全專案重建計畫精煉版
├── agent-teams-plan.md          ← Team 配置總覽
├── 100-migration-foundation/    ← Phase 1
├── 102-multi-format-loaders/    ← Phase 2
├── 103-chat-history-persistence/← Phase 2
├── 104-quality-eval-hallucination/← Phase 2
└── 105-ui-integration/          ← Phase 3
```

> 編號 101 保留給未來 spec。
