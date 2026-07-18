"""
tools/mlops_trigger.py
=========================
イベント駆動のMLOps起動トリガー(Epic 3)。

ローカルDB(なぞかけDPO/SFT候補)とログディレクトリ(Nazo-Agent成功修復ログ)を
スキャンし、閾値を超えたら対応するMLOpsパイプラインをサブプロセスで起動する。

条件A: なぞかけDPO/SFT候補(tools/extract_dataset.pyと同一の抽出条件:
       human_evaluations が1件以上 または is_golden_data=True)の「未学習」件数が
       閾値(settings.mlops_trigger_nazo_threshold、既定500件)以上
       -> tools/mlops_pipeline_nazo.py を起動
条件B: Nazo-Agent成功修復ログ(tools/dataset/agent_sft.jsonlの行数。
       tools/nazo_agent.pyが自己修復に成功するたびに1行追記される)の
       「未学習」件数が閾値(settings.mlops_trigger_agent_threshold、既定50件)以上
       -> tools/mlops_pipeline_agent.py を起動

両閾値ともtools/config.pyのToolsSettingsで定義し、環境変数(.env)経由の上書きを
許可する(モジュール内のマジックナンバーとしてハードコードしない)。

「未学習」の判定について: どちらの候補集合にも「学習済みフラグ」は存在しないため、
前回この条件でトリガーした時点の件数を状態ファイル(STATE_PATH)に記録し、
「現在の件数 - 前回トリガー時点の件数」を未学習件数とみなす。これにより、
閾値を一度超えた後にずっと超え続けている状態で毎スキャンごとに再起動してしまう
多重発火を防ぐ(パイプラインが成功した時点でのみ状態を更新する)。

両方の条件を満たした場合は順次起動する(A→B)。VRAM_LOCK_PATHが1本のグローバル
ロックのため、どうせ同時には実行できない(片方が排他待ちになるだけ)ため、
順次実行の方が意図が明確で、ログも追いやすい。

使い方:
    uv run python tools/mlops_trigger.py             # スキャンし、条件を満たせば起動
    uv run python tools/mlops_trigger.py --dry-run    # 起動せず判定結果のみ表示
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from tools import process_manager  # noqa: E402
from tools.config import settings  # noqa: E402
from tools.extract_dataset import _fetch_candidates  # noqa: E402

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

STATE_PATH = Path(__file__).resolve().parent / "mlops_trigger_state.json"
AGENT_SFT_PATH = BASE_DIR / "tools" / "dataset" / "agent_sft.jsonl"


def _load_state() -> dict:
    if not STATE_PATH.exists():
        return {"nazo_last_triggered_count": 0, "agent_last_triggered_count": 0}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def _save_state(state: dict) -> None:
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def count_nazo_candidates() -> int:
    """tools/extract_dataset.pyと同一条件のなぞかけDPO/SFT候補の総件数を数える。"""
    candidates = asyncio.run(_fetch_candidates())
    return len(candidates)


def count_agent_success_logs() -> int:
    """Nazo-Agent成功修復ログ(agent_sft.jsonlの行数)を数える。ファイルが無い場合は0件。"""
    if not AGENT_SFT_PATH.exists():
        return 0
    with AGENT_SFT_PATH.open(encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def _launch_pipeline(script_name: str) -> bool:
    """パイプラインスクリプトをサブプロセスとして起動し、完了を待つ。戻り値は成功したか。"""
    print(f"\n🚀 [Trigger] {script_name} を起動します...")
    with process_manager.ManagedProcess(
        ["uv", "run", "python", f"tools/{script_name}"], cwd=str(BASE_DIR)
    ) as proc:
        stdout, stderr = proc.communicate()
        returncode = proc.returncode

    if stdout:
        print(stdout, end="")
    if stderr:
        print(stderr, end="")

    if returncode != 0:
        print(f"⚠️  {script_name} が異常終了しました(code={returncode})。")
        return False
    print(f"✅ {script_name} が正常終了しました。")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="MLOpsイベント駆動起動トリガー")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="実際にパイプラインを起動せず、判定結果のみ表示する",
    )
    args = parser.parse_args()

    state = _load_state()

    nazo_total = count_nazo_candidates()
    nazo_pending = nazo_total - state["nazo_last_triggered_count"]
    print(
        f"📊 [条件A] なぞかけDPO/SFT候補: 総数={nazo_total} / "
        f"前回トリガー時={state['nazo_last_triggered_count']} / "
        f"未学習={nazo_pending} (閾値={settings.mlops_trigger_nazo_threshold})"
    )

    agent_total = count_agent_success_logs()
    agent_pending = agent_total - state["agent_last_triggered_count"]
    print(
        f"📊 [条件B] Nazo-Agent成功修復ログ: 総数={agent_total} / "
        f"前回トリガー時={state['agent_last_triggered_count']} / "
        f"未学習={agent_pending} (閾値={settings.mlops_trigger_agent_threshold})"
    )

    nazo_should_trigger = nazo_pending >= settings.mlops_trigger_nazo_threshold
    agent_should_trigger = agent_pending >= settings.mlops_trigger_agent_threshold

    if not nazo_should_trigger and not agent_should_trigger:
        print("\nℹ️  いずれの条件も未達のため、パイプラインは起動しません。")
        return 0

    if args.dry_run:
        if nazo_should_trigger:
            print("🧪 [dry-run] 条件Aが成立: mlops_pipeline_nazo.py を起動する想定です。")
        if agent_should_trigger:
            print("🧪 [dry-run] 条件Bが成立: mlops_pipeline_agent.py を起動する想定です。")
        return 0

    # 両方成立していても順次実行する(VRAMロックが1本のため同時実行しても排他待ちになるだけ)。
    if nazo_should_trigger:
        if _launch_pipeline("mlops_pipeline_nazo.py"):
            state["nazo_last_triggered_count"] = nazo_total
            _save_state(state)

    if agent_should_trigger:
        if _launch_pipeline("mlops_pipeline_agent.py"):
            state["agent_last_triggered_count"] = agent_total
            _save_state(state)

    return 0


if __name__ == "__main__":
    sys.exit(main())
