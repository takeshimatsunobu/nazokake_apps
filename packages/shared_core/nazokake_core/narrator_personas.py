"""
nazokake_core/narrator_personas.py
=====================================
persona_feature_plan_v3.md Phase4: 語り手ペルソナ(narrator persona)のデータ化。

Firestoreを SSoT とする(§3.1)。2つのコレクションを扱う:

  narrator_personas/{persona_id}
      ペルソナ自体の「今」の状態(表示名・所有者・削除可否・現在バージョン等)。
      継続的にUpdateされる(TriggerStateORM等と同じ「1行を更新し続ける」型)。

  narrator_persona_versions/{version_id}
      設定内容(settings)のスナップショット。追記専用(Append-only)。

【不変性の担保 — 内容ハッシュをIDにする(§3.3)】
    version_id = f"{persona_id}__{sha256(canonical_json(settings))[:16]}"
内容が変われば version_id が変わるため、既存バージョンの上書きが原理的に
起こらない。同一内容の再保存は同一IDへの冪等な書き込みとなり、no-op判定も
自動で成立する。

書き込み口は本モジュールの create_persona() / save_persona_settings() の
2関数のみとし、バージョン「更新」関数は定義しない(既存バージョンは常に
不変・追記専用のため、更新という概念自体が存在しない)。

【現時点のスコープ(Phase4)】
本モジュールはデータ層の基盤のみを提供する。実際の参照経路の切り替え
(apps/evaluator/backend・workers/ondemand_elyza_worker.py・apps/persona_main_function
の生成パスがこのコレクションを実際に読みに行くようにする配線)はPhase5
「生成パスへの記録」の対象であり、本モジュールでは行わない。Phase4時点での
本モジュールの唯一の呼び出し元は tools/seed_narrator_personas.py(組み込み
10体+センチネルの投入)である。
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

NARRATOR_PERSONAS_COLLECTION = "narrator_personas"
NARRATOR_PERSONA_VERSIONS_COLLECTION = "narrator_persona_versions"

# センチネル: narrator_persona_idが「不明・未判定」であることを表す固定ID
# (packages/shared_core/nazokake_core/database.py の
# NazokakeItemORM.narrator_persona_id の server_default と同じ値、Phase3参照)。
SENTINEL_PERSONA_ID = "No_Data"

# 組み込みペルソナ(PERSONAS[1..10])のpersona_idは文字列"1"〜"10"に統一する(§7.3)。
SYSTEM_OWNER_UID = "SYSTEM"


def canonical_json(settings: dict[str, Any]) -> str:
    """settingsを安定した(キー順序に依存しない)JSON文字列へ正規化する。

    内容ハッシュ(version_id)の計算に使う唯一の直列化経路。dictのキー挿入順序が
    呼び出し元ごとに揺れても同一内容なら常に同一バイト列になることを保証する。
    """
    return json.dumps(settings, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def compute_content_hash(settings: dict[str, Any]) -> str:
    """settingsの内容ハッシュ(先頭16文字)を返す。"""
    digest = hashlib.sha256(canonical_json(settings).encode("utf-8")).hexdigest()
    return digest[:16]


def compute_version_id(persona_id: str, settings: dict[str, Any]) -> str:
    """§3.3の不変ID設計: version_id = f"{persona_id}__{content_hash}"。"""
    return f"{persona_id}__{compute_content_hash(settings)}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _version_exists(db, version_id: str) -> bool:
    return db.collection(NARRATOR_PERSONA_VERSIONS_COLLECTION).document(version_id).get().exists


def _next_version_no(db, persona_id: str) -> int:
    """persona_idに紐づく既存バージョン数+1を返す(追記専用コレクションのため、
    単純なカウントで一意な連番が得られる)。
    """
    docs = (
        db.collection(NARRATOR_PERSONA_VERSIONS_COLLECTION)
        .where(filter=_field_filter("persona_id", "==", persona_id))
        .stream()
    )
    return sum(1 for _ in docs) + 1


def _field_filter(field: str, op: str, value: Any):
    """firebase_admin.firestore.FieldFilterの遅延import(モジュール読み込み時に
    firebase_adminの初期化を要求しないため、関数内でimportする)。
    """
    from firebase_admin import firestore

    return firestore.FieldFilter(field, op, value)


def _write_version_if_missing(
    db, persona_id: str, version_id: str, settings: dict[str, Any]
) -> None:
    """version_idのドキュメントが存在しなければ新規作成する(既に存在する場合は
    内容ハッシュが一致=同一内容のため、何もしない。これが「同一内容の再保存は
    同一IDへの冪等な書き込みとなる」の実体)。
    """
    if _version_exists(db, version_id):
        return
    version_no = _next_version_no(db, persona_id)
    db.collection(NARRATOR_PERSONA_VERSIONS_COLLECTION).document(version_id).set(
        {
            "version_id": version_id,
            "persona_id": persona_id,
            "version_no": version_no,
            "settings": settings,
            "content_hash": compute_content_hash(settings),
            "created_at": _now_iso(),
        }
    )


def create_persona(
    db,
    owner_uid: str,
    settings: dict[str, Any],
    *,
    display_name: str,
    persona_id: str | None = None,
    base_persona_id: str | None = None,
    is_builtin: bool = False,
    is_deletable: bool = True,
    is_visible: bool = True,
    sort_order: int = 0,
) -> tuple[str, str]:
    """新規ペルソナを作成する(§3.3)。

    persona_id省略時は新規UUIDを発行する(Phase6のユーザー作成ペルソナ用)。
    組み込みペルソナ("1"〜"10")やセンチネル("No_Data")のような固定IDを持つ
    ペルソナは、persona_idを明示的に渡す(tools/seed_narrator_personas.py参照)。

    戻り値: (persona_id, version_id)。
    """
    resolved_persona_id = persona_id or str(uuid.uuid4())
    version_id = compute_version_id(resolved_persona_id, settings)
    now = _now_iso()

    _write_version_if_missing(db, resolved_persona_id, version_id, settings)

    db.collection(NARRATOR_PERSONAS_COLLECTION).document(resolved_persona_id).set(
        {
            "persona_id": resolved_persona_id,
            "owner_uid": owner_uid,
            "owner_display_name": None,
            "display_name": display_name,
            "base_persona_id": base_persona_id,
            "is_builtin": is_builtin,
            "is_deletable": is_deletable,
            "is_visible": is_visible,
            "current_version_id": version_id,
            "sort_order": sort_order,
            "created_at": now,
            "updated_at": now,
            "deleted_at": None,
        }
    )
    return resolved_persona_id, version_id


def save_persona_settings(db, persona_id: str, settings: dict[str, Any]) -> str:
    """既存ペルソナへ新しい設定を保存する(§3.3)。

    内容が変われば新しいversion_idが発行され、narrator_personas側の
    current_version_idがそちらを指すよう更新される(created_at/owner_uid等の
    不変な項目には触れない)。内容が変わらなければ内容ハッシュが同一のため
    version自体は新規作成されず、current_version_idの更新のみが行われる
    (実質no-op、冪等)。

    persona_idは事前にcreate_persona()で作成済みであることを前提とする
    (このモジュールではpersona_id自体の存在確認は行わない。呼び出し元が
    404判定等を担当する設計、nazokake_core.personas.get_persona_or_raiseと
    同じ責務分離)。

    戻り値: version_id。
    """
    version_id = compute_version_id(persona_id, settings)
    _write_version_if_missing(db, persona_id, version_id, settings)

    db.collection(NARRATOR_PERSONAS_COLLECTION).document(persona_id).update(
        {
            "current_version_id": version_id,
            "updated_at": _now_iso(),
        }
    )
    return version_id


# ------------------------------------------------------------------
# persona_feature_plan_v3.md Phase6: マイペルソナAPI(apps/persona_main_function)向けの
# 読み取り・軽量な状態更新ヘルパー。
#
# 【create_persona/save_persona_settingsとの関係】モジュール冒頭のdocstringが
# 定める「書き込み口はcreate_persona()/save_persona_settings()の2関数のみ」は
# narrator_persona_versions(バージョン内容)への書き込みについての制約であり、
# 「バージョン更新関数は定義しない」もこれと同じ文脈(不変バージョンの上書きを
# 禁じる)。ここに追加する関数群はnarrator_personas文書自身の付随フィールド
# (deleted_at/sort_order)のみを更新し、バージョン内容には一切触れないため、
# その制約の対象外として扱う(いずれもこのモジュールに閉じ込め、
# apps/persona_main_function側から生のFirestore書き込みをさせないという設計原則は
# 維持する)。
# ------------------------------------------------------------------


def get_persona(db, persona_id: str) -> dict | None:
    """persona_idに対応するnarrator_personas文書を1件取得する(存在しなければNone)。

    【ディープ監査#4】Firestore接続障害時、ビルトイン解決経路(nazokake_core.
    personas.get_personas)は既にハードコードPERSONASへのフォールバックを
    持つが、この関数(マイペルソナ解決経路)には保護が無く、例外がそのまま
    _resolve_persona_for_generation()を素通りしてapi/deps.py::handle_exceptionsの
    汎用ハンドラまで伝播していた。ここで捕捉してNoneへ縮退させることで、
    呼び出し元の「見つからない場合は404」という既存の分岐へ自然に合流させる
    (黙示のビルトインへのフォールバックはしない、§7.3の方針を維持)。
    """
    try:
        snapshot = db.collection(NARRATOR_PERSONAS_COLLECTION).document(persona_id).get()
    except Exception as e:
        logger.warning(f"⚠️ narrator_personas({persona_id})の取得に失敗しました: {e}")
        return None
    if not snapshot.exists:
        return None
    return snapshot.to_dict()


def get_persona_version(db, version_id: str) -> dict | None:
    """version_idに対応するnarrator_persona_versions文書を1件取得する
    (存在しなければNone)。settings(map)を取り出すための読み取り専用ヘルパー。

    【persona_feature_plan_v3.md Phase7で追加】編集フォームへ現在の設定値を
    プリフィルする(apps/persona_main_function/api/routers/personas.py::_to_item経由)
    ために必要になった。9エンドポイントの契約自体は変えず、既存の
    GET /v1/personasのレスポンスを拡充する形で使う。

    【ディープ監査#4】get_persona()と同じ理由でFirestore接続障害時はNoneへ縮退する。
    """
    try:
        snapshot = db.collection(NARRATOR_PERSONA_VERSIONS_COLLECTION).document(version_id).get()
    except Exception as e:
        logger.warning(f"⚠️ narrator_persona_versions({version_id})の取得に失敗しました: {e}")
        return None
    if not snapshot.exists:
        return None
    return snapshot.to_dict()


def list_visible_personas(db, owner_uid: str) -> list[dict]:
    """§6.2「参照可: is_builtin==true ∪ owner_uid==自分」に該当する文書を、
    論理削除(deleted_at is not None)を除いてsort_order昇順で返す。

    Firestoreの複合クエリ(OR + 削除フィルタ)は追加のインデックスを要求し得るため、
    OR条件のみFirestore側(firestore.Or)で絞り込み、削除フィルタと整列は
    件数の少なさ(実運用でも高々数百件規模)を踏まえてPython側で行う。
    """
    from firebase_admin import firestore

    query_filter = firestore.Or(
        [
            firestore.FieldFilter("is_builtin", "==", True),
            firestore.FieldFilter("owner_uid", "==", owner_uid),
        ]
    )
    docs = db.collection(NARRATOR_PERSONAS_COLLECTION).where(filter=query_filter).stream()
    all_docs = [d.to_dict() or {} for d in docs]
    visible = [
        data
        for data in all_docs
        if not data.get("deleted_at") and data.get("is_visible", True)
    ]
    visible.sort(key=lambda p: (p.get("sort_order", 0), p.get("persona_id", "")))
    return visible


def list_popular_personas(db, limit: int = 10, offset: int = 0) -> list[dict]:
    """「みんなの人気ペルソナ」: カスタムペルソナ(is_builtin==False)を
    usage_count(利用回数)の降順で返す(同数の場合はcreated_at降順=新しい方を
    先に出す)。zabuton_count(獲得座布団数)は将来的なランキング拡張用に
    文書へ持たせたまま返すが、現時点では並び順の決定には使わない。

    件数の少なさ(list_visible_personasと同じ前提、1ユーザーあたり最大5件)を
    踏まえてPython側でソートする(Firestoreのorder_byは対象フィールドを持たない
    ドキュメントを暗黙に除外してしまうため、increment_usage_countが
    まだ一度も呼ばれていない新規ペルソナがランキングから消えてしまう問題を
    避ける狙いもある)。
    """
    docs = (
        db.collection(NARRATOR_PERSONAS_COLLECTION)
        .where(filter=_field_filter("is_builtin", "==", False))
        .stream()
    )
    candidates = [d.to_dict() or {} for d in docs]
    visible = [
        p for p in candidates if not p.get("deleted_at") and p.get("is_visible", True)
    ]
    visible.sort(
        key=lambda p: (p.get("usage_count", 0), p.get("created_at", "")),
        reverse=True,
    )
    return visible[offset : offset + limit]


def increment_usage_count(db, persona_id: str) -> None:
    """persona_idのusage_count(なぞかけ生成に使われた回数)を1加算する
    (persona_feature_plan_v3.md改修要件: みんなの人気ペルソナAPI)。

    Firestoreのfirestore.Increment(1)はフィールドが未存在でも0起点として扱う
    ため、既存ペルソナ文書への事前バックフィルは不要。呼び出し元(生成API)の
    本処理を失敗させないよう、失敗はここで吸収する(カウンタ更新はベスト
    エフォート、なぞかけ生成自体の成否とは独立させる)。
    """
    from firebase_admin import firestore

    try:
        db.collection(NARRATOR_PERSONAS_COLLECTION).document(persona_id).update(
            {"usage_count": firestore.Increment(1)}
        )
    except Exception:
        pass


def increment_zabuton_count(db, persona_id: str) -> None:
    """persona_idのzabuton_count(獲得座布団数)を1加算する。increment_usage_count
    と同じ理由でベストエフォート(失敗を握りつぶす)。"""
    from firebase_admin import firestore

    try:
        db.collection(NARRATOR_PERSONAS_COLLECTION).document(persona_id).update(
            {"zabuton_count": firestore.Increment(1)}
        )
    except Exception:
        pass


def count_owned_personas(db, owner_uid: str) -> int:
    """owner_uidが所有する(論理削除されていない)ペルソナ数を返す(§6: 上限5件チェック用)。"""
    docs = (
        db.collection(NARRATOR_PERSONAS_COLLECTION)
        .where(filter=_field_filter("owner_uid", "==", owner_uid))
        .stream()
    )
    return sum(1 for d in docs if not (d.to_dict() or {}).get("deleted_at"))


def soft_delete_persona(db, persona_id: str) -> None:
    """論理削除する(deleted_atに現在時刻を設定するのみ、文書自体は残す)。

    削除可否の判定(owner_uid/is_deletable、§6.2)は呼び出し元(APIルーター)の
    責務とする(この関数自身はポリシーを持たない、他の書き込み関数と同じ設計)。
    """
    db.collection(NARRATOR_PERSONAS_COLLECTION).document(persona_id).update(
        {"deleted_at": _now_iso(), "updated_at": _now_iso()}
    )


def reorder_personas(db, ordered_persona_ids: list[str]) -> None:
    """指定した順序でsort_orderを振り直す(0始まりの連番)。

    対象の絞り込み(§6.2「並替可: 自分から見える範囲のみ」)は呼び出し元が
    ordered_persona_idsそのものを検証済みである前提とする(この関数はポリシーを
    持たない)。
    """
    batch = db.batch()
    for index, persona_id in enumerate(ordered_persona_ids):
        doc_ref = db.collection(NARRATOR_PERSONAS_COLLECTION).document(persona_id)
        batch.update(doc_ref, {"sort_order": index, "updated_at": _now_iso()})
    batch.commit()


def next_sort_order_for_new_persona(db, owner_uid: str) -> int:
    """新規作成時の並び順(§8.3: 現在の最小値-1)。既存行を1件もUPDATEせずに
    先頭挿入できる。該当行が無ければ0を返す。
    """
    docs = (
        db.collection(NARRATOR_PERSONAS_COLLECTION)
        .where(filter=_field_filter("owner_uid", "==", owner_uid))
        .stream()
    )
    sort_orders = [d.to_dict().get("sort_order", 0) for d in docs if not (d.to_dict() or {}).get("deleted_at")]
    return (min(sort_orders) - 1) if sort_orders else 0
