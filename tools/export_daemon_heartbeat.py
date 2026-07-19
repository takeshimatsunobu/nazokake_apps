"""
tools/export_daemon_heartbeat.py
===================================
mlops-scheduler(tools/scheduler_daemon.py)の生存監視タイル用の静的JSONダンプ
ジェネレーター(instructions/169)。

「フライホイールの稼働確認やエラー監視をSSH接続なしにブラウザの管理画面上で完結
させたい」というSRE要件に基づき、tools/export_metrics.pyと全く同じ設計(CQRS・
静的JSON・アトミック書き込み・schema_versionによるGraceful Degradation)を、
デーモン自身の生存確認(パイプラインの実行結果ではなく、「デーモンが最後にいつ
ポーリングし、何を決定したか」)へ拡張する。

tools/export_metrics.pyが可視化する「パイプラインが実際に走った結果」とは独立した
関心事である: tools/mlops_trigger.pyがどの閾値も満たさず何も起動しなかった(正常系)
場合、metrics.jsonは更新されないため、admin.html単体では「静かで健全」と「静かに
壊れている」を区別できない。この静的JSONはその区別を提供する。

使い方:
    uv run python tools/export_daemon_heartbeat.py   # 手動スモークテスト用
    (通常はtools/scheduler_daemon.pyから関数として呼ばれる)
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

HEARTBEAT_OUTPUT_DIR = BASE_DIR / "apps" / "evaluator" / "frontend" / "public" / "data"
HEARTBEAT_OUTPUT_PATH = HEARTBEAT_OUTPUT_DIR / "daemon_heartbeat.json"
HEARTBEAT_TMP_PATH = HEARTBEAT_OUTPUT_DIR / "daemon_heartbeat.tmp.json"
SCHEMA_VERSION: Literal["1.0"] = "1.0"

Status = Literal["ok", "skipped", "error", "unknown"]


class DaemonHeartbeatSchema(BaseModel):
    """apps/evaluator/frontend/public/data/daemon_heartbeat.jsonのデータコントラクト。

    admin.jsはfetch直後にschema_versionを検証し、想定外の値であればパース・描画を
    中止する(tools/export_metrics.py.DashboardMetricsSchemaと同じ契約)。
    """

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    generated_at: str
    last_cycle_started_at: str | None = None
    last_cycle_finished_at: str | None = None
    status: Status
    message: str


def _atomic_write_json(payload: str, tmp_path: Path, final_path: Path) -> None:
    """一時ファイルへ書き込み+os.fsyncでディスクへの書き込みを確実にした直後、
    os.replaceで目的のファイルへ不可分にすげ替える(tools/export_metrics.pyと同じ
    アトミック書き込みパターン)。読み取り側(admin.jsのfetch)が書き込み途中の
    不完全なJSONを掴むRace Conditionを構造的に防ぐ。
    """
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, final_path)


def export_heartbeat(
    *,
    status: Status,
    message: str,
    last_cycle_started_at: str | None = None,
    last_cycle_finished_at: str | None = None,
) -> Path:
    """デーモンの生存状況を静的JSONへアトミックに書き出し、出力先パスを返す。"""
    schema = DaemonHeartbeatSchema(
        generated_at=datetime.now(timezone.utc).isoformat(),
        last_cycle_started_at=last_cycle_started_at,
        last_cycle_finished_at=last_cycle_finished_at,
        status=status,
        message=message,
    )
    _atomic_write_json(
        schema.model_dump_json(indent=2), HEARTBEAT_TMP_PATH, HEARTBEAT_OUTPUT_PATH
    )
    return HEARTBEAT_OUTPUT_PATH


def main() -> int:
    path = export_heartbeat(status="unknown", message="手動実行によるスモークテストです。")
    print(f"✅ デーモン生存監視の静的JSONをアトミックに書き出しました: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
