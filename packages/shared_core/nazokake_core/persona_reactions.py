"""
nazokake_core/persona_reactions.py
=====================================
persona_feature_plan_v3.md Phase8 §5.5: 第2層(反応)データセット基盤。

【設計変更の背景】従来のapps/persona_main_function/api/routers/timeline.pyは、
「座布団」リアクションを nazokake_results.{doc_id}.zabuton_count への単純な
firestore.Increment(1)で数えていた。この方式は合計値(集計後の数値)しか
残らず、「誰が」「いつ」「どの語り手ペルソナの作品に」反応したかという
個々の反応イベント自体が失われるため、反応データを学習データセット(第2層)
として使えない。本モジュールは「1反応=1レコードの追加」(persona_reactions
コレクションへのInsert-only)へ切り替える書き込み口を提供する。

【既存のzabuton_countとの関係】§5.5の指示により、既存カウント
(nazokake_results.{doc_id}.zabuton_count)は今後インクリメントせず、
「この切り替え以前に蓄積された反応数」を表す初期値(baseline)として凍結する。
以後の反応はすべてpersona_reactionsへの新規ドキュメントとして記録され、
ある対象の「総反応数」は baseline(凍結されたzabuton_count) +
persona_reactionsの件数、で算出する(effective_reaction_count参照)。

書き込み口はこのモジュールの add_reaction() のみとし、呼び出し元
(apps/persona_main_function)がFirestoreへ直接書き込むことはしない
(narrator_personas.pyと同じ設計原則)。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .dataset_envelope import build_envelope

PERSONA_REACTIONS_COLLECTION = "persona_reactions"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def add_reaction(
    db,
    *,
    target_collection: str,
    target_doc_id: str,
    narrator_persona_id: str,
    narrator_persona_version_id: str,
    data_origin: str,
    owner_uid: str | None,
    reaction_type: str = "zabuton",
) -> str:
    """反応を1件、Insert-onlyでpersona_reactionsへ追記する(§5.1の共通エンベロープ適用)。

    戻り値: 新規作成したpersona_reactionsドキュメントのID。
    """
    doc_ref = db.collection(PERSONA_REACTIONS_COLLECTION).document()
    envelope = build_envelope(
        dataset_layer="reaction",
        source_collection=target_collection,
        source_doc_id=target_doc_id,
        narrator_persona_id=narrator_persona_id,
        narrator_persona_version_id=narrator_persona_version_id,
        data_origin=data_origin,
        owner_uid=owner_uid,
        created_at=_now_iso(),
        payload={"reaction_type": reaction_type},
    )
    doc_ref.set(envelope)
    return doc_ref.id


def count_reactions(
    db, *, target_doc_id: str | None = None, reaction_type: str | None = None
) -> int:
    """persona_reactionsの件数を数える(管理コクピットの層別集計・単一対象の
    実効反応数算出の両方から使う汎用ヘルパー)。target_doc_id/reaction_typeは
    指定した条件のみ絞り込む(両方Noneなら全件)。

    【防御的実装】apps/evaluator/backend/api/routers/admin_health.py::
    _count_firestore_sync()と同じ理由(等価フィルタでも未作成の複合インデックスが
    必要になるケースがあり、放置するとFailedPrecondition/その他の例外が
    そのまま呼び出し元(FastAPIレスポンス組み立て中)へ伝播してしまう)により、
    集計自体の失敗はここで吸収し0を返す(呼び出し元を巻き込んでリクエスト全体を
    失敗させない)。
    """
    from firebase_admin import firestore

    query = db.collection(PERSONA_REACTIONS_COLLECTION)
    if target_doc_id is not None:
        query = query.where(
            filter=firestore.FieldFilter("source_ref.doc_id", "==", target_doc_id)
        )
    if reaction_type is not None:
        query = query.where(
            filter=firestore.FieldFilter("payload.reaction_type", "==", reaction_type)
        )
    try:
        return query.count().get()[0][0].value
    except Exception:
        return 0


def effective_reaction_count(db, *, baseline: int, target_doc_id: str) -> int:
    """ある対象の実効反応数 = 移行前の凍結カウント(baseline) + 移行後に
    persona_reactionsへ追記された件数。"""
    return baseline + count_reactions(db, target_doc_id=target_doc_id)


def get_layer_summary(db) -> dict[str, Any]:
    """管理コクピット向け: 第2層(反応)の件数サマリ(§6)。"""
    return {"total_reactions": count_reactions(db)}
