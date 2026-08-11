"""
models/schemas.py
====================
ペルソナ推定とルーティングシステムのPydanticスキーマ契約(骨組み)。
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

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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
    persona_id: int = Field(..., ge=1, le=10, description="nazokake_core.personas.PERSONASのキー(1〜10)")
    # 【段階的ブロック機能で追加】frontend/state.js::ensureUid()がlocalStorageで
    # 生成・保持する匿名UUIDをそのまま送る。認証情報ではなくただの識別文字列であり、
    # クリアされれば別人として扱われる(スプーフィング耐性は低いが、軽量な匿名
    # システムとして許容する設計判断)。services/penalty.pyのブロック判定・
    # ルートBカウントの主キーとして使う。
    client_uuid: str = Field(..., min_length=1, max_length=100, description="クライアント側で生成・保持する匿名UUID")


class GenerateRoutedResponse(BaseModel):
    """POST /v1/generate のレスポンスボディ。"""

    model_config = ConfigDict(extra="forbid")

    doc_id: str = Field(
        ...,
        description="Firestore(nazokake_results)に保存したドキュメントID。route='BLOCKED'の場合は生成自体が行われないため空文字",
    )
    odai: str
    persona_id: int
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


# ------------------------------------------------------------
# GET /v1/personas: フロントエンドのペルソナ選択UI用(骨組み)。
#
# 【SSoT注記】ペルソナの実体(prompt本文含む)は nazokake_core.personas.PERSONAS が
# 唯一の情報源。フロントエンドがこれを二重管理すると、GEMINI_API_KEYの複製事故
# (apps/persona_router/env.py参照)やAPI_BASEの複製事故(evaluator/frontend/
# config.js参照)と同種の「値の食い違い」を将来必ず起こす。そのため本APIは
# 表示に必要な最小限(id/name)のみを都度返し、prompt本文(生成ロジックの内部
# 詳細)はクライアントへ渡さない。
# ------------------------------------------------------------
class PersonaListItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    persona_id: int = Field(..., ge=1, le=10)
    name: str = Field(..., description="表示用のペルソナ名(nazokake_core.personas.PERSONASの'name')")


class PersonaListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    personas: list[PersonaListItem]


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
    persona_id: int
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


# ------------------------------------------------------------
# POST /v1/corrections: 「赤ペン」添削の送信(Phase3)。
#
# 元のAI生成(nazokake_results.{original_doc_id})に対する人間の添削案を保存する。
# 元テキスト(rejected相当)と添削後テキスト(chosen相当)の両方を1ドキュメントに
# 保存しておくことで、将来のDPOペア抽出(apps/evaluator/backend/scripts/
# extract_dpo_data.py相当)がこのコレクションを直接読むだけで
# {prompt, chosen, rejected} を組み立てられるようにする(SSoT: 元テキストの
# 複製は「その時点のスナップショット」として意図的に許容する。nazokake_results側が
# 後から変わることは無いため食い違いは発生しない)。
# ------------------------------------------------------------
class CorrectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    original_doc_id: str = Field(..., min_length=1, description="nazokake_results のドキュメントID")
    client_uuid: str = Field(..., min_length=1, max_length=100)
    pen_name: str = Field(..., min_length=1, max_length=30, description="添削者のペンネーム(localStorage保存)")
    corrected_toku: str = Field(..., min_length=1, max_length=200)
    corrected_kokoro: str = Field(..., min_length=1, max_length=400)


class CorrectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    correction_id: str
    original_doc_id: str
    submitted_at: str = Field(..., description="ISO8601(UTC)")
