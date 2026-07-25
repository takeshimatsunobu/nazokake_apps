from pydantic import BaseModel, Field
from typing import Any, Dict, List, Literal, Optional


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


# --- 道場破りフィード/管理画面のレスポンス契約(nazokake_core.database._row_to_ui_dict と1:1) ---
# 【絶対制約】クラウド同期状態(sync_status/last_sync_error)はUI向け契約に含めない。
class FeedItem(BaseModel):
    doc_id: str
    id: Optional[str] = None
    odai: str
    result: Optional[Dict[str, Any]] = None
    nazokake_text: Optional[str] = None
    scores: Optional[Dict[str, Any]] = None
    s_total: Optional[float] = None
    overall: Optional[str] = None
    axis_comments: Optional[Dict[str, Any]] = None
    message: Optional[str] = None
    reasoning: Optional[str] = None
    evaluated_at: Optional[str] = None
    result_gemini: Optional[Dict[str, Any]] = None
    llmjp_status: Optional[str] = None
    result_llmjp: Optional[Dict[str, Any]] = None
    nazokake_text_llmjp: Optional[str] = None
    scores_llmjp: Optional[Dict[str, Any]] = None
    s_total_llmjp: Optional[float] = None
    overall_llmjp: Optional[str] = None
    axis_comments_llmjp: Optional[Dict[str, Any]] = None
    source: Optional[str] = None
    model_id: Optional[str] = None
    evaluator_model_id: Optional[str] = None
    persona: Optional[Dict[str, Any]] = None
    trend: Optional[Dict[str, Any]] = None
    dpo_pair_id: Optional[str] = None
    created_at: Optional[str] = None
    schema_version: Optional[str] = None
    feed_ready: bool = True
    status: str = "pending"
    eval_status: Optional[str] = None
    is_user_edited: bool = False
    is_golden_data: bool = False
    is_approved: bool = False
    random_weight: Optional[float] = None
    gemini_status: Optional[str] = None
    elyza_status: Optional[str] = None
    locked_at: Optional[str] = None
    completed_at: Optional[str] = None
    result_doc_ids: Optional[List[str]] = None
    human_evaluations: Optional[List[Dict[str, Any]]] = None
    updated_at: Optional[str] = None


class FeedItemsResponse(BaseModel):
    items: List[FeedItem]


class StatusResponse(BaseModel):
    status: str


class AdminActionResponse(BaseModel):
    status: str
    data: FeedItem


# api.deps.handle_exceptions は async ハンドラの想定外例外を握って
# {"status": "error", "message": ...} を200で返す(HTTPExceptionへ変換しない既存挙動)。
# response_model併用時にこの形も正当なレスポンスとして許容するための共用スキーマ。
class ErrorEnvelope(BaseModel):
    status: str
    message: str


# --- DLQ(Dead Letter Queue)管理画面: sync_status=="fatal"に隔離されたアイテムの
# 可視化とリカバリ操作用の契約。FeedItemと異なり、隔離理由そのものを見せるのが目的の
# ため sync_status/last_sync_error/retry_count を意図的に含める。
class DlqItem(BaseModel):
    doc_id: str
    odai: str
    sync_status: str
    last_sync_error: Optional[str] = None
    retry_count: int = 0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class DlqListResponse(BaseModel):
    items: List[DlqItem]


class DlqActionRequest(BaseModel):
    doc_id: str
    action: Literal["retry", "discard"] = Field(
        ...,
        description="DLQに対する操作('retry'=再同期対象へ復帰 / 'discard'=隔離維持のまま非表示化)",
    )


class DlqActionResponse(BaseModel):
    status: str
    doc_id: str
    action: Literal["retry", "discard"]


# --- 監査証跡(Audit Trail): DLQ操作等の破壊的操作をappend-onlyで記録したログの
# 読み取り専用ビュー。DlqActionと同一トランザクションで書き込まれる(database.py側)。
class AuditLogItem(BaseModel):
    id: str
    target_item_id: str
    actor: str
    action: str
    reason: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None


class AuditLogListResponse(BaseModel):
    items: List[AuditLogItem]


# --- 1-Click Deploy(instructions/172、No-Toilの徹底): 検証サーバーへのワンタッチ
# デプロイ(tools/deploy/run_verification_server.ps1)をバックグラウンドで起動する
# エンドポイントの契約。ローカル開発環境専用(Cloud Run上のデプロイ済みコンテナには
# frontend/・PowerShell/gcloud CLIが存在しないため機能しない)。
class AdminDeployResponse(BaseModel):
    status: str
    message: str
    committed_files: List[str] = Field(default_factory=list)
    log_path: str
