"""
api/routers/generate.py
==========================
POST /v1/generate: Step1(キャッシュ確認/推論) → Step2(分岐・生成) → Firestore保存を
同期的に処理して結果を返すエンドポイント。

【設計方針】
既存の apps/evaluator/backend とは異なり、この新サービスはLocal-First
(ローカルSQLiteが正でFirestoreは一方向バックアップ)の前提を採用しない。
Firestoreへ直接・同期的に読み書きする、状態を持たないCloud Runサービスとして
設計する(要件で明示された「同期的に処理して結果を返す」に合わせるため)。
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_db
from models.persona_schemas import GenerateRoutedRequest, GenerateRoutedResponse
from nazokake_core import narrator_personas
from nazokake_core.personas import get_personas
from services.penalty import build_blocked_response, check_block_status, record_route_b
from services.step1_cache import get_cached_step1, put_step1_cache
from services.step1_estimation import estimate_step1
from services.step2_generation import generate_step2

router = APIRouter()

# 正常系(ルートA)・異常系(ルートB)ともに、生成結果は同じコレクションへ保存する
# (要件2)。異常系は is_valid_for_training=false を必ず付与し、学習データ抽出
# バッチ(apps/evaluator/backend/scripts/extract_*.py 相当)側で除外できるようにする。
RESULTS_COLLECTION = "nazokake_results"


class _ResolvedPersona:
    """generate_routed()内で使う、ビルトイン/マイペルソナ双方を統一的に扱うための
    解決結果。settingsは少なくとも"prompt"キーを持つ(ビルトインは{name,prompt}の
    2キーのみ、マイペルソナはPersonaSettingsInputの全項目)。"""

    __slots__ = ("settings", "version_id", "display_name", "data_origin")

    def __init__(self, settings: dict, version_id: str, display_name: str, data_origin: str) -> None:
        self.settings = settings
        self.version_id = version_id
        self.display_name = display_name
        self.data_origin = data_origin


def _resolve_persona_for_generation(db, persona_id: str) -> _ResolvedPersona:
    """persona_idからビルトイン/マイペルソナいずれかの設定を解決する
    (persona_feature_plan_v3.md Phase5「生成パスへの記録」)。

    【ビルトイン("1"〜"10")を優先的にnazokake_core.personas経由で解決する理由】
    管理コクピットのpersona_overrides(プロンプト動的上書き)は、この経路
    (get_personas(db))を通してのみ反映される(§7.2)。narrator_personas
    コレクションにも同じID("1"〜"10")でシード済みだが、そちらを見に行くと
    上書きが反映されなくなってしまうため、数字IDは常にget_personas(db)を
    優先する。

    見つからない場合は404を返す(§7.3: 不明なIDをID:1へ黙ってすり替える
    フォールバックは廃止する。記録上のpersona_idと実際に使われたペルソナが
    食い違う事故を防ぐため)。
    """
    if persona_id.isdigit():
        builtin = get_personas(db).get(int(persona_id))
        if builtin is not None:
            version_id = narrator_personas.compute_version_id(
                persona_id, {"display_name": builtin["name"], "prompt": builtin["prompt"]}
            )
            return _ResolvedPersona(builtin, version_id, builtin["name"], "builtin")

    custom = narrator_personas.get_persona(db, persona_id)
    if custom is not None and not custom.get("deleted_at"):
        version_id = custom.get("current_version_id", "")
        version = narrator_personas.get_persona_version(db, version_id) if version_id else None
        settings = (version or {}).get("settings") or {}
        if settings.get("prompt"):
            display_name = custom.get("display_name") or settings.get("display_name", "")
            return _ResolvedPersona(settings, version_id, display_name, "custom")

    raise HTTPException(status_code=404, detail=f"不明なpersona_id: {persona_id}")


@router.post("/v1/generate", response_model=GenerateRoutedResponse)
async def generate_routed(req: GenerateRoutedRequest, db=Depends(get_db)):
    # --- 段階的ブロックの事前チェック(最優先。Step1/Step2のLLM呼び出しより前に
    # 必ず行う。荒らしユーザーに対してAPI課金を発生させ続けないための設計) ---
    block_status = check_block_status(db, req.client_uuid)
    if block_status.blocked:
        toku, kokoro, nazokake_text = build_blocked_response(req.odai, block_status.blocked_until)
        return GenerateRoutedResponse(
            doc_id="",
            odai=req.odai,
            persona_id=req.persona_id,
            route="BLOCKED",
            toku=toku,
            kokoro=kokoro,
            nazokake_text=nazokake_text,
            is_valid_for_training=False,
            step1_cache_hit=False,
            blocked_until=block_status.blocked_until,
        )

    # 【Phase5】ビルトイン(nazokake_core.personas、管理コクピットの動的上書き込み)
    # とマイペルソナ(nazokake_core.narrator_personas)の双方を統一的に解決する。
    # 存在しないIDは404(§7.3、フォールバック廃止)。
    resolved = _resolve_persona_for_generation(db, req.persona_id)
    persona = resolved.settings
    narrator_persona_id = req.persona_id
    narrator_persona_version_id = resolved.version_id
    narrator_persona_name = resolved.display_name
    data_origin = resolved.data_origin

    # --- Step1: キャッシュ確認 → ミス時のみLLM推定 ---
    step1 = get_cached_step1(db, req.odai)
    step1_cache_hit = step1 is not None
    if step1 is None:
        # 【Phase3】コスト計装の追加に伴いasync化(services/step1_estimation.py参照)。
        step1, estimator_model_id = await estimate_step1(req.odai)
        put_step1_cache(db, req.odai, step1, estimator_model_id)

    # --- Step2: ルート決定(step1.is_valid_input)・生成・全文組み立てはこの関数の内部で行う ---
    # 【Phase3】コスト計装の追加に伴いasync化(services/step2_generation.py参照)。
    route, toku, kokoro, nazokake_text, generator_model_id = await generate_step2(
        req.odai, step1, persona, db=db
    )

    # --- 段階的ブロック: ルートB(異常入力)発生をカウントする ---
    # ここで新たな段階(5回ごと)に到達してもblocked_untilは「次回以降」の
    # リクエストから効き始める(今回の生成・保存はそのまま正常に完了させる)。
    if route == "B":
        record_route_b(db, req.client_uuid)

    # --- Firestore保存(正常系・異常系とも同一コレクション) ---
    doc_id = uuid.uuid4().hex
    doc = {
        "doc_id": doc_id,
        "odai": req.odai,
        "persona_id": req.persona_id,
        # persona_feature_plan_v3.md Phase5 §3.4/§3.5: 生成に実際に使われた
        # ペルソナのID・バージョン・表示名・出自を記録する(narrator_persona_id は
        # persona_idと同一文字列の論理参照だが、SQLite側nazokake_itemsの4列命名
        # (narrator_persona_id/_version_id/_name/data_origin)に揃えて明示的な
        # フィールドとしても持たせる。timeline.py::add_zabuton()は従来どおり
        # persona_id経由でも同じ情報を再導出できるため後方互換)。
        "narrator_persona_id": narrator_persona_id,
        "narrator_persona_version_id": narrator_persona_version_id,
        "narrator_persona_name": narrator_persona_name,
        "data_origin": data_origin,
        # 【Phase2追加】管理コクピットの直談判レビュー(apps/evaluator/backend/
        # api/routers/admin_review.py)が「このクライアントが何を書いてブロック
        # されたか(犯行現場)」をapi/routers/unlock.py::submit_unlock_request()から
        # 逆引きできるようにするための紐付けキー。生成時点では既存の挙動に一切
        # 影響しない(追記のみ)。
        "client_uuid": req.client_uuid,
        "route": route,
        "toku": toku,
        "kokoro": kokoro,
        "nazokake_text": nazokake_text,
        "is_valid_for_training": route == "A",
        "step1_cache_hit": step1_cache_hit,
        "step1_snapshot": step1.model_dump(),
        "generator_model_id": generator_model_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        # api/routers/timeline.pyの「座布団」リアクション用カウンタ。0始まり。
        "zabuton_count": 0,
    }
    db.collection(RESULTS_COLLECTION).document(doc_id).set(doc)

    # 【みんなの人気ペルソナAPI】マイペルソナ(data_origin=="custom")による有効な
    # 生成(ルートA)のみをusage_countとして計上する(ブロック済み・異常入力の
    # エンタメ応答は「利用」として数えない)。ベストエフォート(narrator_personas.
    # increment_usage_count内部で失敗を吸収)のため、失敗しても生成レスポンス
    # 自体には一切影響しない。
    if data_origin == "custom" and route == "A":
        # 【ディープ監査#2】increment_usage_count()は同期関数でFirestoreへ
        # ブロッキングI/Oを行うため、asyncio.to_threadでラップしイベント
        # ループを塞がないようにする(この呼び出し中は同一プロセスの他リクエストが
        # 一切処理されなくなる問題への対処)。
        await asyncio.to_thread(narrator_personas.increment_usage_count, db, narrator_persona_id)

    return GenerateRoutedResponse(
        doc_id=doc_id,
        odai=req.odai,
        persona_id=req.persona_id,
        route=route,
        toku=toku,
        kokoro=kokoro,
        nazokake_text=nazokake_text,
        is_valid_for_training=doc["is_valid_for_training"],
        step1_cache_hit=step1_cache_hit,
    )
