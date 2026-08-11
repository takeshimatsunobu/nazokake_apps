"""
nazokake_core/fewshots.py
=============
Few-shot例文プールの共有アクセス基盤(Phase5/6: フィードバックループ統合)。

管理コクピット(Ⅱペイン)で review_status="golden" と評価され、かつFew-shot採用
タグ(fewshot_axis_tag)が確定したなぞかけを、apps/evaluator/backend側が
Firestoreの FEWSHOT_COLLECTION コレクションへPushする(services/generation.py
から呼ぶ側ではなくapi/routers/admin_review.pyが書き手)。実際にプロンプトへ
注入する側(apps/persona_router、およびapps/evaluator/backend自身の生成
パイプライン)は、本モジュールの get_fewshot_pool(db) 経由でTTLキャッシュ付きに
読む。

【instructions/Phase5-6 デプロイ後の実機障害で発覚・修正】当初 FEWSHOT_COLLECTION は
"nazokake_fewshots" という名前を使っていたが、これは既に別機能(埋め込みベクトル
{content, metadata, embedding} を持つ、本モジュールとは無関係なRAG/ベクトル検索系の
既存コレクション、firestore.indexes.jsonのnazokake_fewshots用ベクトルインデックスは
その機能のもの)が使用中だった。本モジュールがこの名前を「空いている」と誤認して
読み取りを共有してしまい、生成リクエストが既存ドキュメントを拾うたびに
`json.dumps()`がFirestoreの`Vector`型(JSON非対応)でTypeErrorを起こし本番で
500エラーを引き起こした(実機ログで確認済み)。他機能と衝突しない専用の
コレクション名へ変更し、かつ読み取り時に既知キーのみを抽出することで、
今後どのような想定外ドキュメントが紛れ込んでも構造的にクラッシュしないようにする。

nazokake_core/personas.py の get_personas()/persona_overrides と全く同じ設計
(Firestoreをホットパスで直接叩かない、TTL遅延評価、失敗時は直前のキャッシュまたは
空プールへフォールバック)を踏襲する。SQLite(apps/evaluator/backend専用のLocal
SSoT)には一切依存しない(apps/persona_routerはSQLiteを持たないステートレスな
Cloud Runサービスのため、このモジュールを介してのみFew-shotデータへアクセスできる)。

【保持するデータ形状について】ここで保持するエントリは、apps/evaluator/backend
既存の services/generation.py が旧来使っていた_FEWSHOT_POOL(CoT全工程
[associations/kakekotoba/shared_essence/surprise_check]を含む重量級の辞書、
Gemini/ELYZA二枚看板の生成スキーマ向け)とは異なり、apps/persona_router
services/step2_generation.py の出力スキーマ(toku/kokoro/nazokake_text)に
合わせた軽量な辞書(odai/toku/kokoro/nazokake_text/fewshot_axis_tag)のみを
保持する。generation.py側もPhase5/6でこのモジュールへ統一されたため、CoT
フィールドは注入されなくなる(旧世代パイプラインのFew-shot例文が浅くなる
トレードオフについては呼び出し元の変更履歴を参照)。
"""
from __future__ import annotations

import os
import random
import time
from datetime import datetime, timezone
from typing import Any

FEWSHOT_COLLECTION = "nazokake_golden_fewshots"

# Firestoreドキュメントから安全に取り出すキーのホワイトリスト(admin_review.py::
# update_fewshot_selectionが実際に書き込むキーと一致させる)。ここに無いキーは
# 読み取り時に無視する(json.dumps()に非対応の型が将来紛れ込んでも、生成の
# ホットパスをクラッシュさせない構造的な防御)。
_FEWSHOT_ENTRY_KEYS = ("odai", "toku", "kokoro", "nazokake_text", "fewshot_axis_tag")

# 5分(既定)ごとにしかFirestoreへ問い合わせない。環境変数で調整可能
# (nazokake_core.personas.PERSONA_CACHE_TTL_SECONDSと同じ設計)。
FEWSHOT_CACHE_TTL_SECONDS = int(os.environ.get("FEWSHOT_CACHE_TTL_SECONDS", "300"))

# nazokake_fewshotsが無制限に肥大化してFirestore読み取りコスト/レイテンシを
# 悪化させないための上限(SQLite側のdatabase.py::_FEWSHOT_CURATED_LIMIT=100と揃える)。
_FEWSHOT_POOL_LIMIT = 100


def push_fewshot_entry_sync(db, doc_id: str, entry: dict[str, Any]) -> None:
    """Golden確定+タグ選択が確定したなぞかけ1件を、Firestoreへ冪等にUpsertする。

    apps/evaluator/backend の api/routers/admin_review.py::update_fewshot_selection
    から呼ばれる(同期関数、呼び出し側でasyncio.to_threadに包むこと)。doc_idは
    SQLite側のnazokake_items.doc_idをそのまま流用する(1対1対応、Firestore側で
    別途複合IDを発行しない)。
    """
    payload = {**entry, "updated_at": datetime.now(timezone.utc).isoformat()}
    db.collection(FEWSHOT_COLLECTION).document(doc_id).set(payload, merge=True)


def remove_fewshot_entry_sync(db, doc_id: str) -> None:
    """Few-shot採用が取り消された(is_fewshot_selected=falseへ戻された)場合、
    Firestore側からもベストエフォートで削除する(失敗しても実害はゴミが残るのみ、
    次回のis_fewshot_selected=True再確定時に上書きされる)。
    """
    try:
        db.collection(FEWSHOT_COLLECTION).document(doc_id).delete()
    except Exception as e:
        print(
            f"⚠️ [nazokake_core.fewshots] Few-shotエントリの削除に失敗しました"
            f"(doc_id={doc_id}、次回選定解除時に再試行される想定): {e}"
        )


def fetch_fewshot_pool_sync(db) -> list[dict[str, Any]]:
    """FEWSHOT_COLLECTIONの全ドキュメントを取得する(キャッシュを経由しない、常に
    最新のFirestore読み取り)。同期API(呼び出し元でスレッド化すること)。

    _FEWSHOT_ENTRY_KEYSにあるキーのみを抽出して返す(想定外の型を持つ未知の
    キーが混入していても、json.dumps()で落ちない安全な辞書へ正規化する)。
    """
    docs = db.collection(FEWSHOT_COLLECTION).limit(_FEWSHOT_POOL_LIMIT).stream()
    pool = []
    for d in docs:
        data = d.to_dict() or {}
        entry = {k: data[k] for k in _FEWSHOT_ENTRY_KEYS if k in data}
        if entry.get("toku") and entry.get("kokoro"):
            pool.append(entry)
    return pool


_cache: list[dict[str, Any]] | None = None
_cache_fetched_monotonic: float = 0.0


def get_fewshot_pool(db=None) -> list[dict[str, Any]]:
    """生成ロジック(ホットパス)向けの、TTLキャッシュ済みFew-shotプール。

    apps/persona_router::services/step2_generation.py や
    apps/evaluator/backend::services/generation.py は、Firestoreを直接叩く代わりに
    この関数を呼ぶ。FEWSHOT_CACHE_TTL_SECONDS(既定300秒)ごとにしかFirestoreへ
    問い合わせない(Cloud Run実行時、リクエストのたびにFirestore読み取りが発生して
    レイテンシが悪化するのを防ぐ)。取得に失敗した場合は直前の有効なキャッシュ、
    それも無ければ空リストへフォールバックする(Few-shotはあくまで生成品質の補助
    であり、Firestore障害で生成そのものが止まることは絶対に避ける、
    nazokake_core.personas.get_personas()と同じ設計思想)。

    同期関数のため、asyncなホットパス(FastAPI等)から呼ぶ場合は呼び出し元で
    asyncio.to_thread()に包むこと(personas.get_personas()と同じ呼び出し規約)。
    """
    global _cache, _cache_fetched_monotonic

    now_monotonic = time.monotonic()
    if _cache is not None and (now_monotonic - _cache_fetched_monotonic) < FEWSHOT_CACHE_TTL_SECONDS:
        return _cache

    try:
        from firebase_admin import firestore

        client = db or firestore.client()
        pool = fetch_fewshot_pool_sync(client)
        _cache = pool
        _cache_fetched_monotonic = now_monotonic
        return pool
    except Exception as e:
        print(f"⚠️ [nazokake_core.fewshots] Few-shotプールの取得に失敗、フォールバックします: {e}")
        return _cache if _cache is not None else []


def sample_fewshot_examples(pool: list[dict[str, Any]], k: int = 3) -> list[dict[str, Any]]:
    """プールからk件をランダム抽出する(純粋関数、I/Oを含まない)。

    プールが空/k件未満でも安全(kはプール件数で上限クランプ、0件なら空リスト)。
    """
    if not pool:
        return []
    return random.sample(pool, min(k, len(pool)))  # noqa: S311 (Few-shot例の多様性確保用、暗号用途ではない)
