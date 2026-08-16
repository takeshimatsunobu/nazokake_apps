from pydantic import BaseModel, Field, field_validator
from typing import Any, Dict, List, Literal, Optional


class HumanSubmitRequest(BaseModel):
    odai: str
    nazokake_text: str
    parent_id: Optional[str] = None


class GenerateRequest(BaseModel):
    odai: str
    # 【2026-08-16改修: メイン画面のマイペルソナ/みんなのペルソナ対応】従来は
    # int(1〜10のビルトインのみ)固定だったが、narrator_personas(マイペルソナ/
    # みんなのペルソナ)のUUID文字列も受け付けるstrへ拡張する
    # (models/persona_schemas.py::GenerateRoutedRequestと同じint→str正規化
    # パターン。既存クライアント(int送信)との互換のため、mode="before"
    # バリデータでintを受理しstrへ正規化する)。
    # 【ディープ監査#3】"/"等のFirestoreドキュメントパス区切り文字を含む値が
    # そのままdb.collection(...).document(persona_id)へ渡ると、意図しない
    # 階層参照になり得るため、英数字・ハイフン・アンダースコアのみを許可する。
    persona_id: str = Field(
        default="1", min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$",
        description="組み込みは\"1\"〜\"10\"の数字文字列、マイペルソナ/みんなのペルソナはUUID文字列(intも互換のため受理)",
    )
    temperature: float = Field(default=0.6, ge=0.0, le=1.0)

    @field_validator("persona_id", mode="before")
    @classmethod
    def _normalize_persona_id(cls, v: object) -> object:
        if isinstance(v, int):
            return str(v)
        return v


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
    # --- Phase5/6: フィードバックループ統合。道場破りフィード側で由来バッジ表示に使う ---
    origin_type: Optional[str] = None
    source_item_id: Optional[str] = None


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


# --- 承認待ちデータ(管理コックピット「承認待ちデータ」パネル): gemini_status/
# elyza_statusのいずれかが"pending"のなぞかけを、キュレーション対象として一覧表示
# するための契約。result/scores等の重いJSON列はレスポンスサイズ抑制のため含めず、
# レビュー判断に必要な最小限のフィールドのみを公開する。
class PendingItem(BaseModel):
    doc_id: str
    odai: str
    gemini_status: Optional[str] = None
    elyza_status: Optional[str] = None
    nazokake_text: Optional[str] = None
    nazokake_text_llmjp: Optional[str] = None
    s_total: Optional[float] = None
    s_total_llmjp: Optional[float] = None
    created_at: Optional[str] = None
    # --- Phase5/6: フィードバックループ統合 ---
    review_status: Optional[str] = None
    origin_type: Optional[str] = None
    source_item_id: Optional[str] = None
    human_evaluations: Optional[List[Dict[str, Any]]] = None
    is_fewshot_selected: Optional[bool] = None
    fewshot_axis_tag: Optional[str] = None


class PendingListResponse(BaseModel):
    items: List[PendingItem]


# --- Phase5/6: Ⅱペインの5段階評価(review_status)。①🏆Goldenを選んだ場合のみ、
# 既存のFewshotUpdateRequest(評価軸タグ選択)でFew-shot採用へ進める。
class ReviewStatusUpdateRequest(BaseModel):
    review_status: Literal["golden", "good", "hmm", "tolerable", "troll"] = Field(
        ..., description="管理者による5段階評価"
    )


class ReviewStatusUpdateResponse(BaseModel):
    status: str
    doc_id: str
    review_status: str


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


# --- なぞかけ研究所(instructions/231, 233): 公開済み記事の一覧・詳細取得の契約。
# 一覧は本文(content)を含めずタイトル/カテゴリのみ(レスポンスサイズ抑制)、
# 詳細のみ本文を含める。
class ResearchArticleSummary(BaseModel):
    article_id: str
    main_category: str
    sub_category: str
    title: str
    created_at: Optional[str] = None


class ResearchArticleListResponse(BaseModel):
    articles: List[ResearchArticleSummary]


class ResearchArticleDetail(BaseModel):
    article_id: str
    main_category: str
    sub_category: str
    title: str
    content: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# --- 1-Click Deploy(instructions/172、No-Toilの徹底): 検証サーバーへのワンタッチ
# デプロイ(tools/deploy/run_verification_server.ps1)をバックグラウンドで起動する
# エンドポイントの契約。ローカル開発環境専用(Cloud Run上のデプロイ済みコンテナには
# frontend/・PowerShell/gcloud CLIが存在しないため機能しない)。
class AdminDeployResponse(BaseModel):
    status: str
    message: str
    committed_files: List[str] = Field(default_factory=list)
    log_path: str


# ------------------------------------------------------------
# Phase 0: 招待・承認ワークフロー(api/routers/admin_auth.py)。
# 完全招待制の管理者認証: 招待URL(トークン付き) → Googleログイン →
# メイン管理者(オーナー)へ承認依頼メール → オーナーが承認、という流れ。
# admin_invites/admin_users の両コレクションともFirestoreに保存する
# (api.deps.verify_admin_token がadmin_usersのstatus=="approved"を必須化する)。
# ------------------------------------------------------------
class InviteCreateRequest(BaseModel):
    email: str = Field(..., min_length=3, description="招待する相手のメールアドレス")


class InviteCreateResponse(BaseModel):
    status: str
    message: str
    invite_url: str = Field(..., description="発行された招待URL(メール送信が失敗した場合の手動共有用)")


class InviteRedeemRequest(BaseModel):
    token: str = Field(..., min_length=1, description="招待URLに含まれるトークン")


class InviteRedeemResponse(BaseModel):
    status: str
    message: str


class AdminApproveResponse(BaseModel):
    status: str
    message: str


class PendingAdminUser(BaseModel):
    uid: str
    email: str
    status: str
    requested_at: Optional[str] = None


class PendingAdminUsersResponse(BaseModel):
    items: List[PendingAdminUser]


# ------------------------------------------------------------
# Phase 1: お知らせバッジ(api/routers/admin_health.py::get_action_required_summary)。
# 「管理者がアクションを起こす必要があるタスク」に絞った件数集計の契約。
# ------------------------------------------------------------
class ActionRequiredCategory(BaseModel):
    total: int = Field(..., description="現在の未処理総数(バッジの本体)")
    new: int = Field(..., description="前回ログイン以降に新規発生した件数(🆕ハイライト用)")


class ActionRequiredSummaryResponse(BaseModel):
    total: int = Field(..., description="4カテゴリ合計(グローバルバッジの数字)")
    unlock: ActionRequiredCategory
    dlq: ActionRequiredCategory
    review: ActionRequiredCategory
    admin_approval: ActionRequiredCategory
    previous_login_at: Optional[str] = Field(
        None, description="今回の集計で基準にしたlast_login_at(ISO8601)。初回ログイン時はnull"
    )
    warning: Optional[str] = Field(
        None,
        description="いずれかのカウント集計がFirestoreクエリ失敗(複合インデックス未作成等)で"
        "0件へ縮退した場合の警告メッセージ。正常時はnull",
    )


class DatasetLayerCount(BaseModel):
    """persona_feature_plan_v3.md §5/§6: 3層データセット基盤の1層分の件数サマリ。"""

    label: str = Field(..., description="表示用ラベル(例: 「第1層(構造)」)")
    total: int = Field(..., description="この層の現在の件数")


class DatasetLayerSummaryResponse(BaseModel):
    structure: DatasetLayerCount
    reaction: DatasetLayerCount
    correction: DatasetLayerCount
    warning: Optional[str] = Field(
        None, description="いずれかの層の集計が失敗し0件へ縮退した場合の警告メッセージ。正常時はnull"
    )


# ------------------------------------------------------------
# Phase 1: APIエラー率(api/routers/admin_health.py::get_api_error_rate)。
# nazokake_core.schemas.SystemCostLog.success を集計するだけで、Cloud Logging等の
# 追加インフラ無しにエラー率を算出する。
# ------------------------------------------------------------
class ApiErrorRateByService(BaseModel):
    service_type: str
    total: int
    failed: int
    error_rate: float


class ApiErrorRateResponse(BaseModel):
    total: int
    failed: int
    error_rate: float
    sample_size: int = Field(..., description="集計対象にしたsystem_costsの直近件数")
    by_service: List[ApiErrorRateByService] = Field(default_factory=list)


# ------------------------------------------------------------
# Phase 2: Ⅱレビュー(api/routers/admin_review.py)。
# ------------------------------------------------------------
class UnlockRequestReviewItem(BaseModel):
    request_id: str
    client_uuid: str
    message: str
    blocked_until_snapshot: Optional[str] = None
    # apps/persona_main_function/api/routers/unlock.py::_find_offending_generation()が
    # 申し立て時点でnazokake_resultsから逆引き・スナップショットしたもの。
    # 見つからなかった場合(まだ一度もルートBを引かずに直談判が送られてきた等の
    # 想定外の経路)はどちらもnull。
    offending_odai: Optional[str] = None
    offending_text: Optional[str] = None
    status: str
    created_at: str


class UnlockRequestListResponse(BaseModel):
    items: List[UnlockRequestReviewItem]
    warning: Optional[str] = Field(
        None,
        description="Firestoreクエリが失敗した場合の警告メッセージ(例: 複合インデックス未作成)。"
        "正常時はnull。この場合itemsは空配列(=クラッシュではなく劣化表示)",
    )


class UnlockActionRequest(BaseModel):
    action: Literal["pardon", "reset", "reject"] = Field(
        ...,
        description="pardon=一時ブロックのみ解除(カウント維持) / reset=カウントごと完全リセット / reject=却下(ペナルティ維持)",
    )


class UnlockActionResponse(BaseModel):
    status: str
    request_id: str
    action: str


class FewshotUpdateRequest(BaseModel):
    is_fewshot_selected: bool
    fewshot_axis_tag: Optional[str] = Field(
        None, description="意外性(S_sur)等、評価軸コード。is_fewshot_selected=falseの場合は無視される"
    )


class FewshotUpdateResponse(BaseModel):
    status: str
    doc_id: str


# ------------------------------------------------------------
# Phase 3: Ⅲコスト管理 - GCPインフラコスト(BigQuery Billing Export日次集計)。
# api/routers/admin_costs.py::sync_gcp_costs / get_gcp_costs。
# ------------------------------------------------------------
class GcpCostBreakdownItem(BaseModel):
    service_description: str
    cost: float


class GcpCostsLatestResponse(BaseModel):
    schema_version: str = "1.0"
    date: Optional[str] = Field(None, description="YYYY-MM-DD。集計対象の請求日(前日分)")
    currency: Optional[str] = Field(None, description="BigQuery Billing Exportが報告する請求通貨(例: JPY, USD)")
    total_cost: float = 0.0
    breakdown: List[GcpCostBreakdownItem] = Field(default_factory=list)
    generated_at: Optional[str] = Field(None, description="このバッチが最後に実行された時刻(ISO8601)")


class GcpCostsSyncResponse(BaseModel):
    status: str
    message: str
    synced_dates: List[str] = Field(default_factory=list)


# ------------------------------------------------------------
# Phase 4: Ⅳ生成設定(api/routers/admin_config.py)。
# ペルソナの3段階ライフサイクル(登録=時限/上書き=永続/クリア)。
# ------------------------------------------------------------
class PersonaConfigItem(BaseModel):
    persona_id: int
    name: str
    prompt: str
    mode: Literal["default", "temporary", "permanent"] = Field(
        ...,
        description="default=ハードコード初期値のまま(上書き無し) / temporary=時限上書き中 / permanent=永続上書き中",
    )
    expires_at: Optional[str] = Field(None, description="mode=='temporary'の場合のみ、失効予定時刻(ISO8601)")
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None


class PersonaConfigListResponse(BaseModel):
    personas: List[PersonaConfigItem]


class PersonaConfigUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, description="未指定時はハードコード初期値の名前を維持")
    prompt: str = Field(..., min_length=1, max_length=4000)
    duration_preset: Literal["24h", "3d", "permanent"] = Field(
        ...,
        description="24h=登録(24時間の時限適用) / 3d=登録(3日間の時限適用) / permanent=上書き(永続適用)",
    )


class PersonaConfigUpdateResponse(BaseModel):
    status: str
    persona_id: int
    mode: str
    expires_at: Optional[str] = None


class PersonaConfigDeleteResponse(BaseModel):
    status: str
    persona_id: int
