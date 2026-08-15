"""
services/step1_cache.py
==========================
Step1(お題のみの分析結果)のFirestoreキャッシュ層(骨組み)。

【コレクション設計】
  コレクション名: step1_estimation_cache
  ドキュメントID: normalize_odai()で正規化したお題文字列のSHA-256ハッシュ
                  (先頭に "s1_" を付与。Firestoreコンソールでの識別性のため)
  理由: お題の生文字列をそのままドキュメントIDにすると、絵文字・改行・極端に
        長い文字列等でFirestoreのドキュメントID制約(1500バイト、特定文字禁止)に
        抵触し得る。ハッシュ化すれば長さ・文字種が常に一定になり安全。
        同時に、表記ゆれ(全角/半角、前後空白、連続空白)を正規化してから
        ハッシュ化することで、「熱い夏」と「熱い夏 」のような些細な差異で
        キャッシュミスにならないようにする。

【保存スキーマ】
{
  "odai_normalized": str,       # 正規化後のお題(デバッグ・目視確認用)
  "step1": {...Step1Resultのdict...},
  "estimator_model_id": str,    # Step1推定に使ったモデルID
  "schema_version": str,        # Step1Resultの形が変わった際の互換性管理用
  "created_at": ISO8601 str,    # 初回作成時刻
  "last_used_at": ISO8601 str,  # 直近キャッシュヒット時刻(毎回更新)
  "hit_count": int,             # 累計ヒット回数(観測・キャッシュ効果測定用)
}

【要検討】キャッシュのTTL/失効ポリシーは未定。odaiの意味自体は基本的に不変
(「猛暑日のかき氷」は明日も同じ連想語で構わないはず)なので無期限運用も
妥当だが、Step1推定プロンプトを改善した際に旧キャッシュへ道連れで古い結果を
返し続けてしまう問題がある。schema_versionを比較して不一致ならキャッシュ
無視・再推定、という運用を推奨(本骨組みでは呼び出し元に判断を委ねる)。
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timezone

from firebase_admin import firestore

from models.persona_schemas import Step1Result

STEP1_CACHE_COLLECTION = "step1_estimation_cache"
STEP1_SCHEMA_VERSION = "2.0.0"  # Step1Resultを7属性スキーマへ全面改訂(1.0.0からの破壊的変更)


def normalize_odai(odai: str) -> str:
    """お題文字列を正規化する(キャッシュキーの安定化)。

    - Unicode正規化(NFKC): 全角英数字→半角、互換文字の統一
    - 前後の空白除去
    - 内部の連続空白を1つに圧縮(なぞかけのお題として意味のある空白は想定しない)
    """
    s = unicodedata.normalize("NFKC", odai)
    s = s.strip()
    s = re.sub(r"\s+", " ", s)
    return s


def cache_key(odai: str) -> str:
    normalized = normalize_odai(odai)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"s1_{digest}"


def get_cached_step1(db, odai: str) -> Step1Result | None:
    """キャッシュヒット時はhit_count/last_used_atを更新してStep1Resultを返す。
    ミス時はNone(呼び出し元がLLM推定→put_step1_cache()で書き込む)。
    """
    doc_ref = db.collection(STEP1_CACHE_COLLECTION).document(cache_key(odai))
    snapshot = doc_ref.get()
    if not snapshot.exists:
        return None

    data = snapshot.to_dict() or {}
    if data.get("schema_version") != STEP1_SCHEMA_VERSION:
        # プロンプト/スキーマ改訂で古いキャッシュと非互換になった場合は無視して
        # 再推定させる(呼び出し元が改めてput_step1_cache()で上書きする)。
        return None

    doc_ref.update(
        {
            "hit_count": firestore.Increment(1),
            "last_used_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    return Step1Result.model_validate(data["step1"])


def put_step1_cache(db, odai: str, step1: Step1Result, estimator_model_id: str) -> None:
    """Step1推定結果を新規キャッシュとして書き込む(初回のみ。update系操作は
    get_cached_step1()側のhit_count更新に限定し、ここではset()で新規作成する)。
    """
    now = datetime.now(timezone.utc).isoformat()
    doc_ref = db.collection(STEP1_CACHE_COLLECTION).document(cache_key(odai))
    doc_ref.set(
        {
            "odai_normalized": normalize_odai(odai),
            "step1": step1.model_dump(),
            "estimator_model_id": estimator_model_id,
            "schema_version": STEP1_SCHEMA_VERSION,
            "created_at": now,
            "last_used_at": now,
            "hit_count": 0,
        }
    )
