from pydantic import BaseModel, Field
from typing import Dict, Literal, Optional


class HumanSubmitRequest(BaseModel):
    odai: str
    nazokake_text: str
    parent_id: Optional[str] = None


class GenerateRequest(BaseModel):
    odai: str


class TelemetryLogRequest(BaseModel):
    user_slug: str
    event_name: str
    duration: Optional[float] = 0.0
    tab_name: Optional[str] = None
    comment: Optional[str] = None  # モデル別評価の自由記述コメント（任意）


# endpoints.py からインライン定義を集約（ご意見箱）
class FeedbackRequest(BaseModel):
    score: int
    comment: str
    user_slug: str = "anonymous"


# admin.py からインライン定義を集約（管理者設定の更新）
class ConfigUpdateRequest(BaseModel):
    temperature: float
    model_name: str
    system_prompt: str
    evaluator_model: Optional[str] = (
        None  # 評価モデル（審査員LLM）。未指定時は既定にフォールバック。
    )


# モデル別ステータス（nazokake_items の gemini_status / elyza_status が取り得る値）
# pending=未評価 / golden=殿堂入り / approved=承認 / rejected=棄却 / deleted=削除 / n/a=対象外(未生成)
MODEL_STATUS_VALUES = ("pending", "golden", "approved", "rejected", "deleted", "n/a")


# RLHFレビュー表からの評価無効化（論理削除＝学習対象からの除外）
class FeedbackInvalidateRequest(BaseModel):
    log_id: str


# --- なぞかけ掲示板用モデル ---
class BoardPostRequest(BaseModel):
    body: str = Field(..., description="掲示板の投稿内容（なぞかけ議論）")
    parent_id: Optional[str] = Field(
        None, description="返信先のスレッドID（親スレッドの場合はnull）"
    )
    category: str = Field("nazokake", description="カテゴリ('nazokake' または 'ai')")


class HumanActionRequest(BaseModel):
    target_slug: str
    model: Literal["gemini", "elyza"] = Field(
        ..., description="キュレーション対象のモデル"
    )
    action: Literal["golden", "approve", "reject", "delete"] = Field(
        ..., description="適用するキュレーションアクション"
    )


# --- Phase 4: ユーザーフィードバック受付(自己進化ループの入力口) ---
class UserFeedbackRequest(BaseModel):
    overall_score: int = Field(..., ge=1, le=5)
    axis_feedback: Dict[str, Literal["good", "bad"]] = Field(default_factory=dict)
    comment: str = Field(default="", max_length=500)
    model_target: Literal["gemini", "elyza"]
