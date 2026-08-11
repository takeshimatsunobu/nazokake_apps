"""scripts/test_pinch_hitter_rate.py
=====================================
「真の代打ロジック」(api/routers/generate.py::process_elyza)の検証スクリプト。

ローカルワーカー(workers/ondemand_elyza_worker.py)が起動していない/応答しない
状況を再現し、Gemini Flash Lite代打(process_elyza_pinch_hitter)が正しい条件
(タイムアウト時のみ)で発火することを、実際のオーケストレーション・コード
(progressive_generate)を10回連続で走らせて検証する。

【モックの範囲】
- _wait_for_elyza_worker_or_none: 実際の65秒待機は行わず、「タイムアウトした」
  結果(None)を即座に返す(=ワーカー未応答を再現。65秒×10回待つのは非現実的な
  ため、待機ロジック自体ではなく分岐ロジックの正しさを検証する)。
- generate_via_gemini / run_evaluation: 実際のGemini APIを叩かず、固定の
  なぞかけ結果を即座に返す(実APIコストを発生させない、決定論的な結果にする)。
- is_budget_exceeded: 常にFalseを返す(Firestore読み取りを避ける)。

K_SERVICE環境変数をこのプロセス内で明示的に設定し、本番(Cloud Run)相当の
分岐(process_elyza内のK_SERVICE判定)を通過させる。

使い方:
    (apps/evaluator/backend で、.venv有効化後)
    python scripts/test_pinch_hitter_rate.py [--runs 10] [--worker-responds]

--worker-responds を付けると、逆にワーカーが制限時間内に応答した場合の
シナリオ(代打が発火しないはずのケース)を検証する(デフォルトは未応答シナリオ)。
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

# main.py と同じ規約でプロジェクトルートをsys.pathへ追加(apps.tactical_cic等の
# 絶対import解決のため、本スクリプト自体は使わないが依存モジュールのimport連鎖で
# 必要になる場合に備える)。
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

os.environ.setdefault("K_SERVICE", "pinch-hitter-rate-test")

from api.routers import generate as generate_module  # noqa: E402
from nazokake_core.database import (  # noqa: E402
    async_get_item,
    async_upsert_item,
    get_session,
    NazokakeItemORM,
)


_FAKE_RESULT = {
    "hint": "テスト用の連想",
    "toku": "テスト解き",
    "kokoro": "テスト用のこころです。",
    "persona_comment": "",
}
_FAKE_EVAL = {
    "scores": {},
    "s_total": 3.0,
    "axis_comments": {},
    "overall": "テスト用講評",
}


async def _fake_generate_via_gemini(odai, persona_prompt=None, temperature_override=None, model_id="gemini-3.5-flash"):
    return dict(_FAKE_RESULT)


async def _fake_run_evaluation(odai, text):
    return dict(_FAKE_EVAL)


async def _worker_never_responds(doc_id, timeout_sec=None, poll_interval_sec=None):
    """実際の待機を行わず、タイムアウト相当の結果(None)を即座に返す。"""
    return None


async def _worker_responds_quickly(doc_id, timeout_sec=None, poll_interval_sec=None):
    """ワーカーが制限時間内に完了した場合を模擬する。"""
    return {
        "elyza_job_status": "completed",
        "llmjp_status": "completed",
        "result_llmjp": dict(_FAKE_RESULT),
        "nazokake_text_llmjp": "「テスト」とかけて、「テスト解き」ととく。",
        "scores_llmjp": {},
        "s_total_llmjp": 3.0,
        "overall_llmjp": "テスト用講評(ワーカー本物)",
        "axis_comments_llmjp": {},
    }


async def _run_once(worker_fn) -> dict:
    doc_id = uuid.uuid4().hex
    pair_id = f"dpo-test-{doc_id[:12]}"
    # api/routers/generate.py::generate_ai()が本番で行う初期行の作成を模擬する
    # (progressive_generate()はこの初期行が既に存在する前提で、後続のupsertは
    # odai等を再送しない差分更新のみを行うため)。
    await async_upsert_item(
        {
            "doc_id": doc_id,
            "odai": "検証用お題",
            "status": "processing",
            "eval_status": "processing",
            "llmjp_status": "pending",
            "elyza_job_status": "pending",
            "message": "AIが生成中...",
            "dpo_pair_id": pair_id,
        }
    )
    with patch.object(generate_module, "_wait_for_elyza_worker_or_none", worker_fn), \
         patch.object(generate_module, "generate_via_gemini", AsyncMock(side_effect=_fake_generate_via_gemini)), \
         patch.object(generate_module, "run_evaluation", AsyncMock(side_effect=_fake_run_evaluation)), \
         patch.object(generate_module, "is_budget_exceeded", AsyncMock(return_value=False)):
        await generate_module.progressive_generate(
            db=None,
            doc_id=doc_id,
            odai="検証用お題",
            pair_id=pair_id,
            persona_prompt="あなたはテスト用のペルソナです。",
            temperature=0.7,
        )
    data = await async_get_item(doc_id)
    return {"doc_id": doc_id, "data": data}


async def _cleanup(doc_ids: list[str]) -> None:
    async with get_session() as session:
        async with session.begin():
            for doc_id in doc_ids:
                row = await session.get(NazokakeItemORM, doc_id)
                if row is not None:
                    await session.delete(row)


async def main(runs: int, worker_responds: bool) -> None:
    worker_fn = _worker_responds_quickly if worker_responds else _worker_never_responds
    scenario = "ワーカーが制限時間内に応答" if worker_responds else "ワーカーが未応答(起動していない/遅延)"
    print(f"シナリオ: {scenario}")
    print(f"K_SERVICE={os.environ.get('K_SERVICE')!r}")
    print(f"{runs}回のモック生成を実行します...\n")

    pinch_hit_count = 0
    doc_ids: list[str] = []
    for i in range(1, runs + 1):
        result = await _run_once(worker_fn)
        doc_ids.append(result["doc_id"])
        data = result["data"] or {}
        is_pinch_hitter = bool(data.get("llmjp_is_pinch_hitter"))
        model_id = data.get("llmjp_model_id")
        llmjp_status = data.get("llmjp_status")
        if is_pinch_hitter:
            pinch_hit_count += 1
        print(
            f"  [{i:2d}/{runs}] llmjp_status={llmjp_status!r:12s} "
            f"is_pinch_hitter={is_pinch_hitter!s:5s} llmjp_model_id={model_id}"
        )

    rate_pct = (pinch_hit_count / runs) * 100 if runs else 0.0
    print(f"\n代打率: {pinch_hit_count}/{runs} ({rate_pct:.1f}%)")

    await _cleanup(doc_ids)
    print(f"検証用に作成した{len(doc_ids)}件のテスト行をローカルDBから削除しました。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--worker-responds", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.runs, args.worker_responds))
