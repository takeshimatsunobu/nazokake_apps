"""
mcp_server.py
=============
Phase 6: Nazo-Agent の生成・評価・DPO自己進化ループを外部AIエコシステムへ
公開するMCP(Model Context Protocol)サーバー。公式Python SDK(mcp)のFastMCPを用い、
Stdio通信で動作する。

公開内容:
    Tools     : generate_nazokake / evaluate_nazokake / trigger_dpo_pipeline
    Resources : nazo://dpo/stats (抽出済みDPOデータセットの件数・内訳)
    Prompts   : evaluation_correction_prompt (Phase4 Lv.2の動的自己補正指示)

起動:
    python mcp_server.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# services/api 等のsibling packageを、どのcwdから起動されても解決できるようにする
# (main.pyはuvicorn経由でcwd=backend前提だが、MCPクライアントは任意のcwdから起動しうるため)。
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

import firebase_admin

if not firebase_admin._apps:
    firebase_admin.initialize_app(options={"projectId": "nazokakeapp-137e5"})

BACKEND_DIR = Path(__file__).resolve().parent
EVALUATOR_DIR = BACKEND_DIR.parent
REPO_ROOT = EVALUATOR_DIR.parent.parent
DPO_DATASET_PATH = EVALUATOR_DIR / "data" / "dpo_dataset.jsonl"
DPO_PIPELINE_SCRIPT = REPO_ROOT / "tools" / "run_dpo_pipeline.py"

mcp = FastMCP("nazo-agent")


# ============================================================
# Tools(ツール実行)
# ============================================================
@mcp.tool()
async def generate_nazokake(odai: str) -> dict:
    """お題(odai)から、なぞかけをGemini(主軸)で生成する。hint/toku/kokoro/thinkingを含む辞書を返す。"""
    from services.generation import generate_via_gemini

    return await generate_via_gemini(odai)


@mcp.tool()
async def evaluate_nazokake(odai: str, nazokake_text: str) -> dict:
    """お題となぞかけ全文を11軸で評価する。scores/s_total/axis_comments/overallを含む辞書を返す。"""
    from services.evaluation import run_evaluation

    return await run_evaluation(odai, nazokake_text)


@mcp.tool()
def trigger_dpo_pipeline(run_training: bool = False) -> str:
    """DPOデータ抽出 -> 学習準備パイプライン(tools/run_dpo_pipeline.py)を起動し、出力ログを返す。

    run_training=False(既定)の場合、batch_factory側は必ず --dry-run で起動され、
    実際のGPU学習は開始されない。run_training=True を指定した場合のみ実学習を許可する。
    ネットワーク到達性の問題等でハングしないよう、タイムアウトを設けている。
    """
    if not DPO_PIPELINE_SCRIPT.exists():
        return f"[error] pipeline script not found: {DPO_PIPELINE_SCRIPT}"

    args = [sys.executable, str(DPO_PIPELINE_SCRIPT)]
    if run_training:
        args.append("--run-training")

    try:
        result = subprocess.run(  # noqa: S603 (argsはsys.executableと固定スクリプトパスのみ。外部入力なし)
            args,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=300,
        )
        status = (
            "success" if result.returncode == 0 else f"failed(exit={result.returncode})"
        )
        return f"[{status}]\n{result.stdout}{result.stderr}"
    except subprocess.TimeoutExpired:
        return (
            "[timeout] run_dpo_pipeline.py が300秒以内に完了しませんでした"
            "(Firestoreへのネットワーク到達性の問題の可能性があります)。"
        )


# ============================================================
# Resources(知識の参照)
# ============================================================
@mcp.resource("nazo://dpo/stats")
def dpo_stats() -> str:
    """抽出済みDPOデータセット(dpo_dataset.jsonl)の件数・source/pair_type別内訳・最終更新日時を返す。"""
    if not DPO_DATASET_PATH.exists():
        return json.dumps(
            {"error": "dpo_dataset.jsonl not found", "path": str(DPO_DATASET_PATH)},
            ensure_ascii=False,
        )

    total = 0
    breakdown: Counter = Counter()
    with open(DPO_DATASET_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            total += 1
            key = f"{row.get('source', 'unknown')}/{row.get('pair_type', 'unknown')}"
            breakdown[key] += 1

    mtime = datetime.fromtimestamp(
        os.path.getmtime(DPO_DATASET_PATH), tz=timezone.utc
    ).isoformat()

    return json.dumps(
        {
            "total_pairs": total,
            "breakdown": dict(breakdown),
            "last_modified_utc": mtime,
            "path": str(DPO_DATASET_PATH),
        },
        ensure_ascii=False,
        indent=2,
    )


# ============================================================
# Prompts(コンテキスト共有)
# ============================================================
@mcp.prompt()
async def evaluation_correction_prompt() -> str:
    """Phase4 Lv.2で動的生成される、なぞかけ評価の自己補正指示プロンプト。

    services.evaluation.update_dynamic_correction_prompt() により実行時に更新される
    最新の値を都度参照する(モジュール属性アクセスにより値のスナップショット化を避ける)。
    """
    import services.evaluation as evaluation

    return await evaluation.get_dynamic_correction_prompt() or (
        "(現在、自己評価の補正指示はありません。過信している軸は検出されていません。)"
    )


if __name__ == "__main__":
    mcp.run()
