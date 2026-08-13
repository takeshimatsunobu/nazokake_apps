"""
nazokake_core/dataset_envelope.py
==================================
persona_feature_plan_v3.md §5.1: 3層(structure/reaction/correction)の
学習データセットに共通するエンベロープ(封筒)構造を1箇所で定義する。

各層の「保存ロジック」は形態が異なる(第1層=抽出スクリプトが書き出すJSONLの
各行、第2層=persona_reactionsコレクションのFirestoreドキュメント、
第3層=赤ペン2系統を読み取り時に統合した結果)が、いずれも本モジュールの
build_envelope()でラップすることで、どの層のデータも同じキー集合
(dataset_layer/schema_version/source_ref/narrator_persona_id/
narrator_persona_version_id/data_origin/owner_uid/created_at/payload)から
辿れることを保証する。
"""

from __future__ import annotations

from typing import Any, Literal

# エンベロープ自体の構造が将来変わった場合に備えた識別子。payload内部の
# スキーマ(第1層ならodai/toku/kokoro等)とは独立してバージョニングする。
ENVELOPE_SCHEMA_VERSION = "1.0"

DatasetLayer = Literal["structure", "reaction", "correction"]


def build_envelope(
    *,
    dataset_layer: DatasetLayer,
    source_collection: str,
    source_doc_id: str,
    narrator_persona_id: str,
    narrator_persona_version_id: str,
    data_origin: str,
    owner_uid: str | None,
    created_at: str,
    payload: dict[str, Any],
    schema_version: str = ENVELOPE_SCHEMA_VERSION,
) -> dict[str, Any]:
    """§5.1の共通エンベロープを組み立てる。

    payload以外の全キーは「このデータがどこから・誰の・どのペルソナ由来で
    生まれたか」を表すメタデータであり、第1層のDPO自己評価除外・寄与上限
    フィルタ(§5.3)や管理コクピットの層別集計(§6)が共通して参照する。
    """
    return {
        "dataset_layer": dataset_layer,
        "schema_version": schema_version,
        "source_ref": {"collection": source_collection, "doc_id": source_doc_id},
        "narrator_persona_id": narrator_persona_id,
        "narrator_persona_version_id": narrator_persona_version_id,
        "data_origin": data_origin,
        "owner_uid": owner_uid,
        "created_at": created_at,
        "payload": payload,
    }
