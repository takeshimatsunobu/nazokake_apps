"""
tools/export_metrics.py
=========================
MLOps推移ダッシュボード用の静的JSONダンプジェネレーター(CQRS)。

本番APIサーバー(FastAPI, apps/evaluator/backend)とMLOps分析環境の依存を完全に
断ち切るため、tools/mlops_experiments.db(実験履歴)から直近EXPORT_LIMIT件をクエリし、
apps/evaluator/frontend/public/data/metrics.json へアトミックに書き出す。管理画面
(admin.html/admin.js)はこの静的JSONを直接fetchするのみで、FastAPI側に専用の
/api/admin/metricsエンドポイントは一切不要(依存を持たない)。

【データコントラクト】出力JSONは DashboardMetricsSchema (schema_version="1.0" を
必ず含む)に従う。フロントエンド(admin.js)はfetch直後にこのschema_versionを検証し、
不一致であればパース・描画を中止してGraceful Degradation(縮退運転)する契約になって
いるため、このバックエンド側の変更(フィールドの追加・削除・型変更)を行う際は
schema_versionを更新すること。

【Validation before Dump】DBから取得した各行を ExperimentRow モデルへ通し、
検証をクリアした行のみをJSONへ含める(スキーマ不整合な行が静的JSONへ紛れ込み、
フロントエンドのパースを予期せず壊すことを構造的に防ぐ)。

【アトミック書き込み】一時ファイル(metrics.tmp.json)へ書き込み、os.fsyncでOSバッファから
ディスクへの書き込みを確実にした直後、os.replaceで目的のファイルへ不可分にすげ替える。
これにより、読み取り側(admin.jsのfetch)が書き込み途中の不完全なJSONを掴んでUIクラッシュ
を起こすRace Conditionを構造的に防ぐ(SSoT_architecture.md 5節 Safe File Operations、
tools/ast_modifier.py._atomic_write_textと同じ設計思想)。

使い方:
    uv run python tools/export_metrics.py
"""

from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from tools.mlops_experiments_db import EXPERIMENTS_DB_PATH, init_experiments_db  # noqa: E402

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

METRICS_OUTPUT_DIR = BASE_DIR / "apps" / "evaluator" / "frontend" / "public" / "data"
METRICS_OUTPUT_PATH = METRICS_OUTPUT_DIR / "metrics.json"
METRICS_TMP_PATH = METRICS_OUTPUT_DIR / "metrics.tmp.json"
EXPORT_LIMIT = 100
SCHEMA_VERSION: Literal["1.0"] = "1.0"


class ExperimentRow(BaseModel):
    """mlops_experimentsテーブルの1行分の出力契約(record_experiment()の列と対応)。"""

    id: int
    timestamp: str
    pipeline_type: str
    dataset_size: int | None = None
    coreset_ratio: float | None = None
    git_commit_hash: str | None = None
    base_model: str | None = None
    success_rate: float | None = None
    latency: float | None = None
    regression_rate: float | None = None


class DashboardMetricsSchema(BaseModel):
    """apps/evaluator/frontend/public/data/metrics.jsonのデータコントラクト。

    admin.jsはfetch直後にschema_versionを検証し、想定外の値であれば
    パース・描画を中止する(Graceful Degradation、instructions/140)。
    """

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    generated_at: str
    rows: list[ExperimentRow]


def fetch_recent_experiments(limit: int = EXPORT_LIMIT) -> list[dict]:
    """mlops_experimentsテーブルの直近limit件を、タイムスタンプ昇順(古い順、折れ線
    グラフの横軸として自然な順序)で取得する。"""
    init_experiments_db()
    con = sqlite3.connect(EXPERIMENTS_DB_PATH)
    try:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT * FROM mlops_experiments ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        con.close()
    return [dict(row) for row in reversed(rows)]


def _validate_rows(raw_rows: list[dict]) -> list[ExperimentRow]:
    """DBから取得した各行をExperimentRowへ通し、検証をクリアした行のみを返す
    (Validation before Dump)。不整合な行は静的JSONへ含めず、標準エラー出力へ
    警告を残すのみに留める(1行の異常でエクスポート全体を失敗させない)。
    """
    validated = []
    for raw_row in raw_rows:
        try:
            validated.append(ExperimentRow.model_validate(raw_row))
        except ValidationError as e:
            print(
                f"⚠️  [export_metrics] スキーマ検証エラーのため1行スキップします: {e}",
                file=sys.stderr,
            )
    return validated


def _atomic_write_json(payload: str, tmp_path: Path, final_path: Path) -> None:
    """一時ファイルへ書き込み+os.fsyncでディスクへの書き込みを確実にした直後、
    os.replaceで目的のファイルへ不可分にすげ替える。
    """
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, final_path)


def export_metrics() -> Path:
    """直近の実験履歴を検証した上で静的JSONへアトミックに書き出し、出力先パスを返す。"""
    raw_rows = fetch_recent_experiments()
    validated_rows = _validate_rows(raw_rows)
    schema = DashboardMetricsSchema(
        generated_at=datetime.now(timezone.utc).isoformat(),
        rows=validated_rows,
    )
    _atomic_write_json(
        schema.model_dump_json(indent=2), METRICS_TMP_PATH, METRICS_OUTPUT_PATH
    )
    return METRICS_OUTPUT_PATH


def main() -> int:
    path = export_metrics()
    print(f"✅ MLOpsメトリクスの静的JSONをアトミックに書き出しました: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
