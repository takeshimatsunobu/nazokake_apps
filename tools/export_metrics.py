"""
tools/export_metrics.py
=========================
MLOps推移ダッシュボード用の静的JSONダンプジェネレーター(CQRS)。

本番APIサーバー(FastAPI, apps/evaluator/backend)とMLOps分析環境の依存を完全に
断ち切るため、tools/mlops_experiments.db(実験履歴)から直近EXPORT_LIMIT件をクエリし、
apps/evaluator/frontend/public/data/metrics.json へアトミックに書き出す。管理画面
(admin.html/admin.js)はこの静的JSONを直接fetchするのみで、FastAPI側に専用の
/api/admin/metricsエンドポイントは一切不要(依存を持たない)。

【アトミック書き込み】一時ファイル(metrics.tmp.json)へ書き込み、os.fsyncでOSバッファから
ディスクへの書き込みを確実にした直後、os.replaceで目的のファイルへ不可分にすげ替える。
これにより、読み取り側(admin.jsのfetch)が書き込み途中の不完全なJSONを掴んでUIクラッシュ
を起こすRace Conditionを構造的に防ぐ(SSoT_architecture.md 5節 Safe File Operations、
tools/ast_modifier.py._atomic_write_textと同じ設計思想)。

使い方:
    uv run python tools/export_metrics.py
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

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


def _atomic_write_json(payload: dict, tmp_path: Path, final_path: Path) -> None:
    """一時ファイルへ書き込み+os.fsyncでディスクへの書き込みを確実にした直後、
    os.replaceで目的のファイルへ不可分にすげ替える。
    """
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, final_path)


def export_metrics() -> Path:
    """直近の実験履歴を静的JSONへアトミックに書き出し、出力先パスを返す。"""
    rows = fetch_recent_experiments()
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rows": rows,
    }
    _atomic_write_json(payload, METRICS_TMP_PATH, METRICS_OUTPUT_PATH)
    return METRICS_OUTPUT_PATH


def main() -> int:
    path = export_metrics()
    print(f"✅ MLOpsメトリクスの静的JSONをアトミックに書き出しました: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
