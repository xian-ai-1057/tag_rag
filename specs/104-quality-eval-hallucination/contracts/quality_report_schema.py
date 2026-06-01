# quality_report_schema — Pydantic v2 Schema
# ---------------------------------------------------------------
# Spec: specs/104-quality-eval-hallucination/spec.md §4, §6
# Owner: spec-author（由 Phase 0 鎖死，後續 teammate 唯讀）
# ---------------------------------------------------------------
"""Post-hoc quality evaluation 的 DTO 契約。

Eval 結果是 `QualityReport`：
  - quality_score：句級 supported 比例（0.0 ~ 1.0）
  - sentence_supports：每句的 support 判定
  - unsupported_entities：被偵測但未在 cited chunks 找到的實體

Spec 104 是純規則式、deterministic、< 500ms、零 LLM、零 NER 依賴。
Schema 在 in-memory 用，未來可選擇序列化進 chat history（v3 backlog；
v2 不持久化）。

Usage:
    from src.eval.report import evaluate
    from src.rag_chain import query

    answer = query("...")
    report = evaluate(answer.answer, answer.retrieved)
    print(report.quality_score)  # 0.8

Fixtures:
    contracts/fixtures/quality_report_supported_example.json
    contracts/fixtures/quality_report_unsupported_example.json
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------
# Enums
# ---------------------------------------------------------------

class EntityKind(StrEnum):
    """偵測到的實體類型（純 regex 推斷）。

    PER / ORG / LOC 在 v2 暫時無 NER，全部歸 `MISC`。NUM / DATE 為主力。
    保留 enum 完整集合是為未來 v3 升級 NER 時不破壞 schema。
    """
    PER = "per"      # 人名（v2 未實作偵測；保留 enum）
    ORG = "org"      # 組織（v2 未實作偵測；保留 enum）
    LOC = "loc"      # 地名（v2 未實作偵測；保留 enum）
    NUM = "num"      # 數值（含 億 / 萬 / % 等量詞）
    DATE = "date"    # 日期（含「YYYY 年」、「YYYY-MM-DD」）
    MISC = "misc"    # 其他（fallback）


# ---------------------------------------------------------------
# SentenceSupport — 句級 support 判定
# ---------------------------------------------------------------

class SentenceSupport(BaseModel):
    """單一句子的 support 判定。

    判定流程（spec §3.2）：
      1. 抓句中 [n] markers
      2. 對應到 cited chunks
      3. 3-gram character overlap
      4. overlap < 0.15 視為 unsupported

    Acceptance:
        - 對應 spec.md §8 AC #1、#3
    """

    model_config = ConfigDict(extra="forbid")

    sentence: str = Field(..., description="原句字串（含 [n] markers）")
    supported: bool = Field(..., description="overlap >= 閾值 0.15")
    best_match_context_id: str | None = Field(
        default=None,
        description="若 supported=True，記錄 overlap 最高的 context_id；無 marker / 不 supported 為 None",
    )
    overlap_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="3-gram character overlap（0.0 ~ 1.0）；無 marker 時為 0.0",
    )


# ---------------------------------------------------------------
# EntityFlag — 未支持的實體
# ---------------------------------------------------------------

class EntityFlag(BaseModel):
    """偵測到但 cited chunks 內找不到的實體。

    判定流程（spec §3.3）：
      1. regex 抓答案內各類實體
      2. 對每實體做 substring 檢查：是否在任何 cited chunk text 內
      3. 若都找不到 → 加入本 list

    Acceptance:
        - 對應 spec.md §8 AC #2
    """

    model_config = ConfigDict(extra="forbid")

    entity: str = Field(..., description="實體字串（直接取 regex match）")
    kind: EntityKind = Field(..., description="實體類型")
    reason: str = Field(
        ...,
        description="為何被 flag（如 'not found in any cited chunk text'）",
    )


# ---------------------------------------------------------------
# QualityReport — 整體報告
# ---------------------------------------------------------------

class QualityReport(BaseModel):
    """Post-hoc quality evaluation 整體報告。

    `quality_score` 是「句級 supported 比例」：
        quality_score = sum(s.supported for s in sentence_supports) / total
    無句子（總數 0）時為 1.0（避免除 0；視為「沒答案 = 無問題」）。

    Acceptance:
        - 對應 spec.md §8 AC #1、#2、#3、#4、#5
        - golden fixtures：
            contracts/fixtures/quality_report_supported_example.json
            contracts/fixtures/quality_report_unsupported_example.json
    """

    model_config = ConfigDict(extra="forbid")

    quality_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="supported 句子比例",
    )
    sentence_supports: list[SentenceSupport] = Field(
        default_factory=list,
        description="逐句 support 判定（順序與答案內出現順序一致）",
    )
    unsupported_entities: list[EntityFlag] = Field(
        default_factory=list,
        description="答案內偵測但 cited chunks 找不到的實體",
    )
