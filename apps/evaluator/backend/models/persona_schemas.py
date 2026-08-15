"""
models/schemas.py
====================
お題属性推定とルーティングシステムのPydanticスキーマ契約(骨組み)。
【命名の是正、persona_feature_plan_v3.md §0】main.pyのdocstring参照。
apps/evaluator/backend/models/schemas.py と同じ配置規約(Request/Responseを
1ファイルに集約)に従う。

【フロー】
  Step1(お題のみの分析・キャッシュ対象): 同じお題なら誰が生成しても結果は同じはず、
    という前提のもと、お題の7つの属性変数(is_valid_input/domain_category/
    vocabulary_difficulty/slang_level/wordplay_flexibility/topic_scale/
    is_seasonal)を1回だけ推定する。is_valid_input=falseがルートB(異常入力)判定
    そのものを兼ねる。
  Step2(ペルソナ反映・生成): Step1の結果とペルソナ(persona_id)を掛け合わせて
    実際のtoku/kokoroを生成する。ルートA(is_valid_input=true)は通常生成、
    ルートB(is_valid_input=false)はis_valid_for_training=falseの学習データ
    非対象生成として扱う。
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

DomainCategory = Literal["school", "work", "hobby", "daily_life", "general_unknown"]
VocabularyDifficulty = Literal["easy", "standard", "advanced"]
SlangLevel = Literal["none", "youth_slang", "jargon"]
WordplayFlexibility = Literal["high", "medium", "low"]
TopicScale = Literal["personal", "social", "global"]


class Step1Result(BaseModel):
    """お題(odai)のみに依存する、ペルソナ非依存の7属性の推定結果。Firestoreキャッシュの
    保存値そのもの(services/step1_cache.pyのSTEP1_CACHE_COLLECTIONドキュメントの
    中核フィールド)。
    """

    model_config = ConfigDict(extra="forbid")

    is_valid_input: bool = Field(
        ..., description="意味の通る言葉か。無意味な文字列・システムへの命令混入等はfalse(ルートB判定を兼ねる)"
    )
    domain_category: DomainCategory = Field(..., description="お題が属するドメイン")
    vocabulary_difficulty: VocabularyDifficulty = Field(..., description="お題の語彙難易度")
    slang_level: SlangLevel = Field(..., description="スラング・専門用語の度合い")
    wordplay_flexibility: WordplayFlexibility = Field(..., description="掛詞として展開しやすいか")
    topic_scale: TopicScale = Field(..., description="話題のスケール(個人的〜世界的)")
    is_seasonal: bool = Field(..., description="季節・行事に関連するお題か")


class GenerateRoutedRequest(BaseModel):
    """POST /v1/generate のリクエストボディ。"""

    model_config = ConfigDict(extra="forbid")

    odai: str = Field(..., min_length=1, max_length=200, description="ユーザーが入力したお題")
    # 【persona_feature_plan_v3.md Phase5 §7.3】persona_idの型をstrへ統一する。
    # 組み込みは"1"〜"10"の数字文字列、マイペルソナ(narrator_personas)はUUID文字列。
    # 既存クライアント(int送信)との互換のため、mode="before"バリデータでintを
    # 受理しstrへ正規化する(Union型にして呼び出し側全体にint|strの分岐を
    # 波及させないための設計判断)。
    persona_id: str = Field(
        ..., min_length=1, max_length=64,
        description="組み込みは\"1\"〜\"10\"の数字文字列、マイペルソナはUUID文字列(intも互換のため受理)",
    )
    # 【段階的ブロック機能で追加】frontend/state.js::ensureUid()がlocalStorageで
    # 生成・保持する匿名UUIDをそのまま送る。認証情報ではなくただの識別文字列であり、
    # クリアされれば別人として扱われる(スプーフィング耐性は低いが、軽量な匿名
    # システムとして許容する設計判断)。services/penalty.pyのブロック判定・
    # ルートBカウントの主キーとして使う。
    client_uuid: str = Field(..., min_length=1, max_length=100, description="クライアント側で生成・保持する匿名UUID")

    @field_validator("persona_id", mode="before")
    @classmethod
    def _normalize_persona_id(cls, v: object) -> object:
        if isinstance(v, int):
            return str(v)
        return v


class GenerateRoutedResponse(BaseModel):
    """POST /v1/generate のレスポンスボディ。"""

    model_config = ConfigDict(extra="forbid")

    doc_id: str = Field(
        ...,
        description="Firestore(nazokake_results)に保存したドキュメントID。route='BLOCKED'の場合は生成自体が行われないため空文字",
    )
    odai: str
    persona_id: str
    route: Literal["A", "B", "BLOCKED"] = Field(
        ...,
        description="A=正常入力 / B=異常入力(is_valid_input=false) / BLOCKED=段階的ペナルティによる一時退場中",
    )
    toku: str
    kokoro: str
    nazokake_text: str
    is_valid_for_training: bool = Field(
        ..., description="学習データ抽出バッチの対象に含めてよいか(ルートB・BLOCKEDは常にfalse)"
    )
    step1_cache_hit: bool = Field(..., description="Step1がキャッシュから取得できたか(観測用)。BLOCKED時は常にfalse")
    blocked_until: str | None = Field(
        None, description="route='BLOCKED'の場合のみ、一時退場の解除予定時刻(ISO8601・UTC)"
    )


# 【persona_feature_plan_v3.md Phase6】GET /v1/personas のレスポンスは
# 旧PersonaListItem/PersonaListResponse(persona_id: int、name/promptのみの
# 簡易形)から、NarratorPersonaItem/NarratorPersonaListResponse(本ファイル
# 末尾、persona_id: str、narrator_personas文書の全付随情報込み)へ置き換えた
# (§7.1「GET /v1/personas: 変更」)。


# ------------------------------------------------------------
# GET /v1/timeline: 公開タイムライン取得(骨組み)。
#
# 【荒らし対策フラグの扱い】is_valid_for_training=falseの異常入力系(ルートB)も
# 意図的に除外せずそのまま返す(「エラーのエンタメ化」の応答自体がコンテンツで
# あり、生成した本人にとっては「自分の作品」でもあるため)。表示可否・見せ方の
# 制御はフロントエンド側の責務とする(要件で明示された分担)。
# ------------------------------------------------------------
class TimelineItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_id: str
    odai: str
    # 【persona_feature_plan_v3.md Phase5】マイペルソナ(narrator_personas)のUUID
    # 文字列を保持したなぞかけも同じコレクションに保存されるため、int固定では
    # ValidationErrorになる(timeline.py::_to_timeline_item参照)。
    persona_id: str
    route: Literal["A", "B"]
    toku: str
    kokoro: str
    nazokake_text: str
    is_valid_for_training: bool
    zabuton_count: int = Field(0, description="「座布団」リアクション数")
    created_at: str = Field(..., description="ISO8601(UTC)。ページネーションのカーソルにも使う")


class TimelineResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[TimelineItem]
    next_before: str | None = Field(
        None,
        description="次ページ取得用カーソル(最後の要素のcreated_at)。これ以上無ければnull",
    )


class ZabutonResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_id: str
    zabuton_count: int


# ------------------------------------------------------------
# POST /v1/unlock-requests: ブロック画面からの「運営へ直談判する」フォーム送信。
#
# 【スコープ注記】このAPIはFirestoreへの記録のみを行い、自動解除は行わない。
# 実際のブロック解除(services/penalty.pyのblocked_untilクリア)は運営が手動で
# 行うことを想定する(自動判定ロジックは本フェーズのスコープ外)。
# ------------------------------------------------------------
class UnlockRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_uuid: str = Field(..., min_length=1, max_length=100)
    message: str = Field(..., min_length=1, max_length=1000, description="運営への言い訳・反省文")


class UnlockRequestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    submitted_at: str = Field(..., description="ISO8601(UTC)")


# 【persona_feature_plan_v3.md Phase9クリーンアップ】POST /v1/corrections用の
# CorrectionCreate/CorrectionResponse(Phase3で新設)は、赤ペン添削の書き込み口が
# evaluator backend側のPOST /feed/evaluate/{doc_id}(SQLite user_akapen系統)へ
# 一本化されたため削除した。旧実装はgit履歴を参照。

# ------------------------------------------------------------
# persona_feature_plan_v3.md Phase6: マイペルソナAPI(§7.1の9エンドポイント)。
#
# 【§7.5 プロンプトインジェクション対策(このモジュールが担う部分)】
# 1. 名前は30文字・改行禁止
# 3. prompt保存時に長さ上限(2000文字)と禁止パターン検査
# ここでの正規表現検査はあくまで補助的な防御(defense in depth)であり、主たる
# 防御は「アプリ側の固定プロンプトを常にユーザープロンプトより後ろに配置する
# (後勝ち構造)」という呼び出し側(services/step2_generation.py等、Phase6の
# スコープ外)の構造そのもの。ここでは、システムプロンプトの構造自体を破壊しようと
# する明確な意図を持つパターン(会話ロールマーカーの偽装・既存指示の無視要求)
# のみを狙い撃ちし、ロールプレイ設定自体(「〜として振る舞ってください」等、
# 本機能の核心)を誤検知しないよう最小限に絞る。
# ------------------------------------------------------------

_INJECTION_PATTERN_SOURCES = [
    # 【修正】"ignore all previous instructions"のように修飾語が複数連続する
    # ケースを取りこぼさないよう、"ignore"と"instructions"の間は語数を限定せず
    # 任意文字(最大20文字、改行またぎの回避策も想定しDOTALLを適用)の緩い
    # ギャップとして扱う。
    r"ignore\s+.{0,20}?\binstructions?\b",
    r"disregard\s+.{0,20}?\b(instructions?|rules?|guidelines?)\b",
    r"system\s*prompt",
    r"system\s*:",
    r"assistant\s*:",
    r"<\|.*?\|>",  # ChatML等の特殊トークン偽装(<|im_start|>等)
    r"###\s*instruction",
    r"(これまで|以上|上記)の(指示|命令|プロンプト)(を|は)?\s*(無視|忘れ|破棄)",
    r"システムプロンプト",
    r"(指示|命令)を?\s*(すべて|全て)\s*(無視|忘れ)",
]
_INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE | re.DOTALL) for p in _INJECTION_PATTERN_SOURCES
]


def _reject_injection_patterns(value: str, *, field_label: str) -> str:
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(value):
            raise ValueError(
                f"{field_label}に、システムプロンプトの構造を乱す可能性のある"
                "パターンが含まれているため保存できません。"
            )
    return value


def _reject_newlines(value: str, *, field_label: str) -> str:
    if "\n" in value or "\r" in value:
        raise ValueError(f"{field_label}に改行を含めることはできません。")
    return value


PersonaTone = Literal["gentle", "energetic", "cool", "warm", "sharp", "playful", "serious"]
PersonaThinkingLevel = Literal["low", "medium", "high"]


class PersonaSettingsInput(BaseModel):
    """narrator_persona_versions.settings に保存する設定項目(§3.2)。

    create/update(POST・PATCH)の入力にも、draft生成の出力にも使う共通の形。
    """

    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(..., min_length=1, max_length=30, description="このペルソナの呼び名です")
    prompt: str = Field(
        ..., min_length=1, max_length=2000,
        description="AIに「あなたは誰か」を教える文章。人格の核になります",
    )
    first_person: str = Field("", max_length=30, description="一人称(僕・私・わし など)")
    speech_style: str = Field("", max_length=200, description="語尾や口調の癖")
    tone: PersonaTone = Field("gentle", description="全体の雰囲気")
    favorite_topics: list[str] = Field(default_factory=list, max_length=20, description="得意なお題のジャンル")
    taboo: list[str] = Field(default_factory=list, max_length=20, description="触れさせたくない話題")
    thinking_level: PersonaThinkingLevel = Field(
        "low", description="AIがどれくらいじっくり考えるか(Geminiのみ)"
    )
    temperature: float = Field(0.8, ge=0.0, le=1.5, description="発想の飛躍度(ELYZAのみ)")

    @field_validator("display_name")
    @classmethod
    def _validate_display_name(cls, v: str) -> str:
        v = _reject_newlines(v, field_label="display_name")
        return _reject_injection_patterns(v, field_label="display_name")

    @field_validator("prompt")
    @classmethod
    def _validate_prompt(cls, v: str) -> str:
        return _reject_injection_patterns(v, field_label="prompt")

    @field_validator("first_person", "speech_style")
    @classmethod
    def _validate_short_text_fields(cls, v: str) -> str:
        return _reject_newlines(v, field_label="このフィールド")

    @field_validator("favorite_topics", "taboo")
    @classmethod
    def _validate_list_fields(cls, v: list[str]) -> list[str]:
        for item in v:
            if len(item) > 50:
                raise ValueError("リスト内の各項目は50文字以内にしてください。")
            _reject_newlines(item, field_label="リスト項目")
        return v


class PersonaCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    settings: PersonaSettingsInput
    base_persona_id: str | None = Field(
        None, description="派生元のpersona_id(既存ペルソナを複製してカスタマイズする場合)"
    )


class PersonaUpdateRequest(BaseModel):
    """PATCH /v1/personas/{id}: 新バージョンを追加する(§3.3、既存バージョンの上書きはしない)。"""

    model_config = ConfigDict(extra="forbid")

    settings: PersonaSettingsInput


class NarratorPersonaItem(BaseModel):
    """narrator_personas文書のAPI公開形(§3.1)。persona_idは文字列(§7.3)。"""

    model_config = ConfigDict(extra="forbid")

    persona_id: str
    display_name: str
    owner_uid: str
    owner_display_name: str | None = None
    base_persona_id: str | None = None
    is_builtin: bool
    is_deletable: bool
    is_visible: bool
    current_version_id: str
    sort_order: int
    created_at: str
    updated_at: str
    # 【persona_feature_plan_v3.md Phase7で追加】current_version_idが指す
    # narrator_persona_versions文書のsettings(§3.2)をそのまま同梱する。
    # 編集フォーム(apps/persona_main_function/frontend/ui/personas.js)がPATCH前に
    # 現在値をプリフィルするために必要(9エンドポイントに単体GETが無いため、
    # 既存のGET /v1/personasのレスポンスを拡充する形で対応する)。
    # バージョン文書が何らかの理由で見つからない場合はNone(呼び出し元は
    # 新規作成同然の空フォームとして扱う)。
    settings: dict | None = None


class PopularPersonaItem(BaseModel):
    """GET /v1/personas/popular の1件分(§改修要件「みんなの人気ペルソナ」)。

    一覧画面での軽量表示に絞り、NarratorPersonaItemが持つsettings/current_version_id
    等の編集用フィールドは含まない。usage_count/zabuton_countは両方とも
    nazokake_core.narrator_personasが管理するベストエフォートのカウンタで、
    ランキング順位はこの2値の合計(popularity_score)で決まる。
    """

    model_config = ConfigDict(extra="forbid")

    persona_id: str
    display_name: str
    owner_display_name: str | None = None
    usage_count: int
    zabuton_count: int
    popularity_score: int


class PopularPersonasResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    personas: list[PopularPersonaItem]


class NarratorPersonaListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    personas: list[NarratorPersonaItem]


class PersonaMutationResponse(BaseModel):
    """POST・PATCH /v1/personas の共通レスポンス。"""

    model_config = ConfigDict(extra="forbid")

    persona_id: str
    version_id: str


class PersonaDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    persona_id: str
    deleted: bool = True


class PersonaOrderRequest(BaseModel):
    """PUT /v1/personas/order: 並び順の一括更新。"""

    model_config = ConfigDict(extra="forbid")

    ordered_persona_ids: list[str] = Field(..., min_length=1, max_length=5)


class PersonaOrderResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ordered_persona_ids: list[str]


class PersonaSchemaField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    type: Literal["string", "enum", "list[string]", "float"]
    applies_to: Literal["both", "gemini", "elyza"]
    tooltip: str


class PersonaSchemaResponse(BaseModel):
    """GET /v1/personas/schema: 設定項目定義+ツールチップ本文(§3.2)。"""

    model_config = ConfigDict(extra="forbid")

    fields: list[PersonaSchemaField]


class PersonaDraftRequest(BaseModel):
    """POST /v1/personas/draft: 名前からGeminiで初期設定を生成する(保存しない、§7.4)。"""

    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(..., min_length=1, max_length=30, description="このペルソナの呼び名です")

    @field_validator("display_name")
    @classmethod
    def _validate_display_name(cls, v: str) -> str:
        v = _reject_newlines(v, field_label="display_name")
        return _reject_injection_patterns(v, field_label="display_name")


class PersonaDraftResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    settings: PersonaSettingsInput
    is_fallback: bool = Field(
        ..., description="Gemini呼び出し・パースに失敗し、空テンプレートへフォールバックした場合true"
    )


class TransferCodeIssueResponse(BaseModel):
    """POST /v1/personas/transfer-code: 引き継ぎコード発行(§6.1)。"""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., description="A3K7-9PQR形式の引き継ぎコード")
    expires_at: str = Field(..., description="ISO8601(UTC)。24時間後")


class TransferCodeApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., min_length=1, max_length=20)


class TransferCodeApplyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transferred_count: int = Field(..., description="所有権が移管されたペルソナ数")
    new_owner_uid: str
