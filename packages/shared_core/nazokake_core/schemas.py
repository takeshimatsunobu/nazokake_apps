"""
batch/schemas.py
================
Firestore nazokake_items コレクション of スキーマ契約を Pydantic で凍結する。
"""
from __future__ import annotations
from datetime import datetime, timezone
import random
from typing import Literal, Dict, Any
from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "1.0.0"
SOURCE_TAG = "batch_factory_gemini"

# ------------------------------------------------------------
# 検問所①: LLM生成直後の最小契約 (Dynamic Few-Shot / RAG用)
# ------------------------------------------------------------
class NazokakeGenerationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    associations: list[str] = Field(default_factory=list)
    kakekotoba: list[str] = Field(default_factory=list)
    shared_essence: str = ""
    surprise_check: str = ""
    toku: str = Field(..., min_length=1)
    kokoro: str = Field(..., min_length=1)

# ------------------------------------------------------------
# メタデータ・スコア・講評モデル群
# ------------------------------------------------------------
class Scores(BaseModel):
    S_sur: float = Field(..., ge=0.0, le=1.0)
    S_tech: float = Field(..., ge=0.0, le=1.0)
    S_emo: float = Field(..., ge=0.0, le=1.0)
    S_rhy: float = Field(..., ge=0.0, le=1.0)
    S_sensory: float = Field(..., ge=0.0, le=1.0)
    S_visual: float = Field(..., ge=0.0, le=1.0)
    S_ontology: float = Field(..., ge=0.0, le=1.0)
    S_cultural: float = Field(..., ge=0.0, le=1.0)
    S_cm: float = Field(..., ge=0.0, le=1.0)
    S_prosody: float = Field(..., ge=0.0, le=1.0)
    S_nat: float = Field(..., ge=0.0, le=1.0)

class Result(BaseModel):
    hint: str = ""
    toku: str
    kokoro: str

# 🚨 私が消してしまっていた Big5 クラスを完全復元
class Big5(BaseModel):
    openness: str
    conscientiousness: str
    extraversion: str
    agreeableness: str
    neuroticism: str

class PersonaMeta(BaseModel):
    occupation_code: str
    occupation_name: str
    big5: Big5
    persona_prompt: str

class TrendMeta(BaseModel):
    odai_word: str
    rss_source: str
    rss_category: str
    article_title: str
    fetched_at: str

# ------------------------------------------------------------
# 検問所②: Firestore 保存スキーマ (= feed.js 契約)
# ------------------------------------------------------------
class NazokakeItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # --- feed.js 互換コア -----------------------------------
    doc_id: str = Field(..., min_length=1)
    id: str = Field(..., min_length=1)
    odai: str = Field(..., min_length=1)
    result: Result
    nazokake_text: str = Field(..., min_length=1)
    scores: Scores
    s_total: float = Field(..., ge=0.0, le=5.0)
    overall: str = Field(..., min_length=1)
    axis_comments: Dict[str, str] = Field(default_factory=dict)

    # --- 工場由来メタ ----------------------------------------
    source: Literal["batch_factory_gemini", "batch_factory_local"] = SOURCE_TAG
    model_id: str = Field(..., min_length=1)
    evaluator_model_id: str = Field(..., min_length=1)
    persona: PersonaMeta
    trend: TrendMeta
    dpo_pair_id: str = Field(default="", description="DPO学習用: GeminiとELYZAのペアを紐付ける共通ID")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    schema_version: str = SCHEMA_VERSION

    # --- Webアプリ連携フラグ (管理コックピット用パスポート) ----
    feed_ready: bool = True
    status: str = "all_completed"
    eval_status: str = "completed"
    is_user_edited: bool = False
    is_golden_data: bool = False
    is_approved: bool = False
    random_weight: float = Field(default_factory=random.random, description="無限スクロールのランダムシーク用乱数")
    gemini_status: str = "pending"
    elyza_status: str = "n/a"

    @model_validator(mode="after")
    def _enforce_consistency(self) -> "NazokakeItem":
        return self

# ------------------------------------------------------------
# 検問所①-b: Gemini 評価出力 (EvaluationOutput)
# ------------------------------------------------------------
class EvaluationOutput(BaseModel):
    scores: dict
    axis_comments: Dict[str, str]
    overall: str
