"""
tools/extract_training_data.py
================================
instructions/241(SSoTバックログ「課題P: DPO/SFT完全自動パイプラインの構築」第一歩):
ローカルSQLite(nazokake_items、instructions/240のFirestoreリストアで復元された
データを含む)から評価完了済み・高品質ななぞかけを抽出し、一般的なインストラクション・
チューニング形式のJSONLへ整形する。

【tools/extract_dataset.pyとの関係】既存の tools/extract_dataset.py は、コアーセット・
リプレイ選定・MinHash LSHによる重複排除・匿名化・chosen/rejectedペア化まで含む
本格的なDPO/SFTパイプライン(出力先: data/sft_dataset.jsonl, data/dpo_dataset.jsonl)を
既に実装済み。本スクリプトはそれを置き換えるものではなく、多くの汎用ファイン
チューニングツールがそのまま読み込める単純な形式をdata/training/ へ別途出力する、
軽量な補助スクリプトとして新設する(instructions/241が指定した出力先・形式に合わせる)。

品質閾値は tools/extract_dataset.py の CHOSEN_SCORE_MIN(5点満点中4.0以上を
高品質とする既存のプロジェクト基準)と揃える。

【persona_feature_plan_v3.md Phase8 §5.1/§5.2】出力形式を「完成文
(「odai」とかけて「toku」と解く。その心はkokoro、という文体込みの1本の文字列)」
から、構造化された odai → toku + kokoro へ変更する。理由は、完成文には
語り手ペルソナの文体(語尾・一人称等)がそのまま焼き込まれてしまい、この
構造(第1層)学習データに特定ペルソナの文体が混入してしまうため(§5参照、
文体の混入は「完成文を使わない」ことで原理的に防ぐ設計)。あわせて§5.1の
共通エンベロープ(dataset_layer等)を各行に適用する。

使い方:
    uv run python tools/extract_training_data.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import firebase_admin
from firebase_admin import firestore
from sqlalchemy import select

from nazokake_core.database import NazokakeItemORM, ensure_db_ready, get_session
from nazokake_core.dataset_envelope import build_envelope
from nazokake_core.narrator_personas import SENTINEL_PERSONA_ID, get_persona

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "data" / "training"
OUTPUT_PATH = OUTPUT_DIR / "nazokake_instruction_tuning.jsonl"

# tools/extract_dataset.py の CHOSEN_SCORE_MIN と揃える(5点満点中)。
QUALITY_SCORE_MIN = 4.0


async def _fetch_qualifying_rows() -> list[dict]:
    """評価が完了している(s_totalが存在し、QUALITY_SCORE_MIN以上)レコードを抽出する。

    §5.2: 完成文(nazokake_text)ではなく、構造化されたtoku/kokoroを個別に取り出す
    ためresult(JSON)列を読む。resultにtoku/kokoroの両方が入っていない行
    (例: 古い世代のデータでresultが空、nazokake_textしか無い)は、完成文からの
    逆算(パース)は文体混入防止という目的に反するため、意図的に除外する。
    """
    async with get_session() as session:
        stmt = select(
            NazokakeItemORM.odai,
            NazokakeItemORM.result,
            NazokakeItemORM.doc_id,
            NazokakeItemORM.narrator_persona_id,
            NazokakeItemORM.narrator_persona_version_id,
            NazokakeItemORM.data_origin,
            NazokakeItemORM.created_at,
        ).where(
            NazokakeItemORM.s_total.is_not(None),
            NazokakeItemORM.s_total >= QUALITY_SCORE_MIN,
            NazokakeItemORM.odai.is_not(None),
        )
        rows = (await session.execute(stmt)).all()

    qualifying = []
    for odai, result, doc_id, narrator_persona_id, narrator_persona_version_id, data_origin, created_at in rows:
        if not odai or not odai.strip():
            continue
        toku = str((result or {}).get("toku") or "").strip()
        kokoro = str((result or {}).get("kokoro") or "").strip()
        if not toku or not kokoro:
            continue
        qualifying.append(
            {
                "odai": odai.strip(),
                "toku": toku,
                "kokoro": kokoro,
                "doc_id": doc_id,
                "narrator_persona_id": narrator_persona_id or SENTINEL_PERSONA_ID,
                "narrator_persona_version_id": narrator_persona_version_id or SENTINEL_PERSONA_ID,
                "data_origin": data_origin or "no_data",
                "created_at": created_at,
            }
        )
    return qualifying


def _resolve_owner_uids(narrator_persona_ids: set[str]) -> dict[str, str | None]:
    """narrator_persona_id -> owner_uid の対応表を作る(§5.1のowner_uidフィールド用)。

    Firestore narrator_personasは高々数十件規模のため、行ごとにクエリせず
    一意なpersona_id集合分だけをキャッシュしながら引く。存在しない/未判定の
    persona_id(センチネル含む)はowner_uid=Noneとする。
    """
    if not firebase_admin._apps:
        firebase_admin.initialize_app(options={"projectId": "nazokakeapp-137e5"})
    db = firestore.client()

    owner_uids: dict[str, str | None] = {}
    for persona_id in narrator_persona_ids:
        persona_doc = get_persona(db, persona_id)
        owner_uids[persona_id] = (persona_doc or {}).get("owner_uid")
    return owner_uids


def main() -> int:
    ensure_db_ready()
    rows = asyncio.run(_fetch_qualifying_rows())

    owner_uids = _resolve_owner_uids({row["narrator_persona_id"] for row in rows})

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        for row in rows:
            envelope = build_envelope(
                dataset_layer="structure",
                source_collection="nazokake_items",
                source_doc_id=row["doc_id"],
                narrator_persona_id=row["narrator_persona_id"],
                narrator_persona_version_id=row["narrator_persona_version_id"],
                data_origin=row["data_origin"],
                owner_uid=owner_uids.get(row["narrator_persona_id"]),
                created_at=row["created_at"] or "",
                payload={"odai": row["odai"], "toku": row["toku"], "kokoro": row["kokoro"]},
            )
            f.write(json.dumps(envelope, ensure_ascii=False) + "\n")

    print(f"✅ {len(rows)}件のインストラクション・チューニングデータを書き出しました: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        # typeshedのsys.stdout/stderrはTextIOとして型付けされreconfigure()を
        # 宣言していないが、実行時は実際にTextIOWrapperであり存在する。
        sys.stdout.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue]
        sys.stderr.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue]
    sys.exit(main())
