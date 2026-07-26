"""
tools/extract_training_data.py
================================
instructions/241(SSoTバックログ「課題P: DPO/SFT完全自動パイプラインの構築」第一歩):
ローカルSQLite(nazokake_items、instructions/240のFirestoreリストアで復元された
データを含む)から評価完了済み・高品質ななぞかけを抽出し、一般的なインストラクション・
チューニング形式({"prompt": お題, "response": なぞかけ回答})のJSONLへ整形する。

【tools/extract_dataset.pyとの関係】既存の tools/extract_dataset.py は、コアーセット・
リプレイ選定・MinHash LSHによる重複排除・匿名化・chosen/rejectedペア化まで含む
本格的なDPO/SFTパイプライン(出力先: data/sft_dataset.jsonl, data/dpo_dataset.jsonl)を
既に実装済み。本スクリプトはそれを置き換えるものではなく、多くの汎用ファイン
チューニングツールがそのまま読み込める単純な{"prompt","response"}形式を
data/training/ へ別途出力する、軽量な補助スクリプトとして新設する
(instructions/241が指定した出力先・形式に合わせる)。

品質閾値は tools/extract_dataset.py の CHOSEN_SCORE_MIN(5点満点中4.0以上を
高品質とする既存のプロジェクト基準)と揃える。

使い方:
    uv run python tools/extract_training_data.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import select

from nazokake_core.database import NazokakeItemORM, ensure_db_ready, get_session

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "data" / "training"
OUTPUT_PATH = OUTPUT_DIR / "nazokake_instruction_tuning.jsonl"

# tools/extract_dataset.py の CHOSEN_SCORE_MIN と揃える(5点満点中)。
QUALITY_SCORE_MIN = 4.0


async def _fetch_qualifying_items() -> list[dict[str, str]]:
    """評価が完了している(s_totalが存在し、QUALITY_SCORE_MIN以上)レコードを抽出する。"""
    async with get_session() as session:
        stmt = select(NazokakeItemORM.odai, NazokakeItemORM.nazokake_text).where(
            NazokakeItemORM.s_total.is_not(None),
            NazokakeItemORM.s_total >= QUALITY_SCORE_MIN,
            NazokakeItemORM.odai.is_not(None),
            NazokakeItemORM.nazokake_text.is_not(None),
        )
        rows = (await session.execute(stmt)).all()
        return [
            {"odai": odai, "nazokake_text": nazokake_text}
            for odai, nazokake_text in rows
            if odai.strip() and nazokake_text.strip()
        ]


def main() -> int:
    ensure_db_ready()
    items = asyncio.run(_fetch_qualifying_items())

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        for item in items:
            record = {"prompt": item["odai"], "response": item["nazokake_text"]}
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"✅ {len(items)}件のインストラクション・チューニングデータを書き出しました: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
