# -*- coding: utf-8 -*-
# 【爆速化(1発入魂アルゴリズム)対応】best-of-N(N=3並行生成→最高得点選抜)+
# DPO選好ログの書き出しはworkers/ondemand_elyza_worker.py::_process_job()から
# 撤去された(1回の生成のみを試みる設計へ変更、比較対象となる複数候補が存在しなく
# なったため)。本スクリプトもそれに合わせて更新した(_mark_failure→
# _mark_immediate_failureへのリネームも反映)。
import asyncio
import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock

sys.path.insert(0, str(Path.cwd()))
from workers.ondemand_elyza_worker import _process_job

async def test_worker_dpo():
    print("🚀 1発入魂 Worker E2E Mock Test Started...")

    dummy_job = {
        'doc_id': 'e2e_test_doc_999',
        'odai': 'SREの心構えについて、Gemma3の視点からなぞかけをお願いします',
        'retry_count': 0,
        'dpo_pair_id': 'dpo_test_pair_001'
    }

    async def mock_generate(*args, **kwargs):
        return {
            "toku": "常に監視を怠らないこと",
            "kokoro": "どちらもアラート（粗とー）が気になります"
        }

    async def mock_evaluate(odai, text):
        return {
            'scores': {'coherence': 10},
            's_total': 10,
            'overall': '良い',
            'axis_comments': {'coherence': 'ロジックのコメント'}
        }

    print("Mocking Firestore and LLM interfaces...")

    with patch('workers.ondemand_elyza_worker.generate_via_llmjp', new=AsyncMock(side_effect=mock_generate)), \
         patch('workers.ondemand_elyza_worker.run_evaluation', new=AsyncMock(side_effect=mock_evaluate)), \
         patch('workers.ondemand_elyza_worker._mark_job_outcome', new=AsyncMock()) as mock_mark_success, \
         patch('workers.ondemand_elyza_worker._mark_immediate_failure', new=AsyncMock()) as mock_mark_fail:

        await _process_job("DUMMY_DB", "DUMMY_COLLECTION", dummy_job)

        if mock_mark_success.called:
            print("✅ _mark_job_outcome was called safely (Firestore bypassed).")
        elif mock_mark_fail.called:
            print("❌ _mark_immediate_failure was called.")

if __name__ == '__main__':
    asyncio.run(test_worker_dpo())