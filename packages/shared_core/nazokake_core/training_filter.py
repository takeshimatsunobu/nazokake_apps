"""nazokake_core/training_filter.py
=====================================
学習データ抽出パイプライン全体で共有する「データポイズニング防止」の唯一の判定
ロジック(SSoT)。

【なぜFirestoreクエリの.where()で済ませないか】
Firestoreの等価フィルタ(`.where("is_valid_for_training", "==", True)`)は、
フィールド自体が存在しないドキュメントを一切マッチさせない(存在しない
フィールドに対する比較は常に不一致として扱われる)。旧来の `nazokake_items`
コレクションのドキュメントには `is_valid_for_training` フィールドがそもそも
存在しないため、サーバー側の`.where()`でこの絞り込みを行うと、汚染とは無関係な
旧データまで学習データ抽出から根こそぎ除外されてしまう。

そのため判定は「フェッチ後にPython側でこの関数を通す」方式に統一する。
フィールドが存在しない場合は「汚染される前から存在する安全なデータ」として
Trueにフォールバックし(=学習対象に含めてよい)、明示的に `False` が書き込まれて
いる場合(apps/persona_main_function/api/routers/generate.py のルートB等)のみを除外する。
"""
from __future__ import annotations


def is_valid_for_training(doc: dict) -> bool:
    """Firestoreドキュメント(dict化済み)が学習データ抽出の対象に含めてよいかを判定する。

    `is_valid_for_training` フィールドが存在しない場合は True(旧データは対象に含める)。
    フィールドが存在し明示的に False の場合のみ除外する(荒らし・異常入力を
    「エンタメ化」した生成物など、学習データに混入させてはいけないもの)。
    """
    return doc.get("is_valid_for_training", True) is not False
