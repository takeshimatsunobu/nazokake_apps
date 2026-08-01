"""
tools/mlops_experiments_db.py
================================
MLOps実験管理DB(Epic 3拡張)。

学習履歴を不変ログ(Append-only、既存行のUPDATE/DELETEは行わない)として記録する、
アプリ本体のDB(nazokake_local.db)とは物理的に完全に分離した独立SQLiteファイル。
アプリのSerialized Writer/非同期セッション管理(nazokake_core.database)には一切
依存しない、単純なsqlite3(標準ライブラリ)ベースの薄いロガーであり、
tools/mlops_pipeline_nazo.py / tools/mlops_pipeline_agent.py がパイプライン完了時に
1回ずつ呼び出す想定。
"""

from __future__ import annotations

import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
EXPERIMENTS_DB_PATH = BASE_DIR / "run" / "mlops_experiments.db"

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS mlops_experiments (
    id INTEGER PRIMARY KEY,
    timestamp TEXT NOT NULL,
    pipeline_type TEXT NOT NULL,
    dataset_size INTEGER,
    coreset_ratio REAL,
    git_commit_hash TEXT,
    base_model TEXT,
    success_rate REAL,
    latency REAL,
    regression_rate REAL
)
"""


def init_experiments_db() -> None:
    """mlops_experiments.dbとmlops_experimentsテーブルを用意する(既存データは保持)。"""
    EXPERIMENTS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(EXPERIMENTS_DB_PATH)
    try:
        con.execute(_CREATE_TABLE_SQL)
        con.commit()
    finally:
        con.close()


def _current_git_commit_hash() -> str | None:
    """現在のHEADのコミットハッシュを取得する(失敗時はNone、記録自体は継続する)。"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def record_experiment(
    *,
    pipeline_type: str,
    dataset_size: int | None = None,
    coreset_ratio: float | None = None,
    base_model: str | None = None,
    success_rate: float | None = None,
    latency: float | None = None,
    regression_rate: float | None = None,
) -> None:
    """1回のパイプライン実行結果を不変ログとして1行INSERTする。

    pipeline_type: "nazo" または "agent"。git_commit_hashとtimestampはこの関数が
    自動的に付与する(呼び出し元が指定する必要はない)。
    """
    init_experiments_db()
    con = sqlite3.connect(EXPERIMENTS_DB_PATH)
    try:
        con.execute(
            """
            INSERT INTO mlops_experiments (
                timestamp, pipeline_type, dataset_size, coreset_ratio,
                git_commit_hash, base_model, success_rate, latency, regression_rate
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                pipeline_type,
                dataset_size,
                coreset_ratio,
                _current_git_commit_hash(),
                base_model,
                success_rate,
                latency,
                regression_rate,
            ),
        )
        con.commit()
    finally:
        con.close()
