# -*- coding: utf-8 -*-
import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock

sys.path.insert(0, str(Path.cwd()))
from workers.ondemand_elyza_worker import _process_job

async def test_worker_dpo():
    print("🚀 Best-of-N Worker E2E Mock Test Started...")

    dummy_job = {
        'doc_id': 'e2e_test_doc_999',
        'odai': 'SREの心構えについて、Gemma3の視点からなぞかけをお願いします',
        'retry_count': 0,
        'dpo_pair_id': 'dpo_test_pair_001'
    }

    score_counter = 0

    async def mock_generate(*args, **kwargs):
        return {
            "toku": "常に監視を怠らないこと",
            "kokoro": "どちらもアラート（粗とー）が気になります"
        }

    async def mock_evaluate(odai, text):
        nonlocal score_counter
        score_counter += 10
        return {
            'scores': {'coherence': score_counter},
            's_total': score_counter,
            'overall': '良い',
            'axis_comments': {'coherence': 'ロジックのコメント'}
        }

    print("Mocking Firestore and LLM interfaces...")
    
    with patch('workers.ondemand_elyza_worker.generate_via_llmjp', new=AsyncMock(side_effect=mock_generate)), \
         patch('workers.ondemand_elyza_worker.run_evaluation', new=AsyncMock(side_effect=mock_evaluate)), \
         patch('workers.ondemand_elyza_worker._mark_job_outcome', new=AsyncMock()) as mock_mark_success, \
         patch('workers.ondemand_elyza_worker._mark_failure', new=AsyncMock()) as mock_mark_fail:

        await _process_job("DUMMY_DB", "DUMMY_COLLECTION", dummy_job)

        if mock_mark_success.called:
            print("✅ _mark_job_outcome was called safely (Firestore bypassed).")
        elif mock_mark_fail.called:
            print("❌ _mark_failure was called.")

    log_file = Path('run/audit_reports/dpo_preference_log.jsonl')
    if log_file.exists():
        print(f"\n📂 DPO Log found at: {log_file}")
        lines = log_file.read_text(encoding='utf-8').strip().split('\n')
        recent_logs = [line for line in lines if line.strip()][-3:]
        
        print("\n--- Latest Data Flywheel (DPO) Logs ---")
        for line in recent_logs:
            data = json.loads(line)
            is_chosen = "⭐ CHOSEN" if data.get('is_chosen') else "❌ REJECTED"
            print(f"[{data.get('doc_id')}] Score: {data.get('s_total')} | {is_chosen}")
    else:
        print("❌ DPO Log file not found!")

if __name__ == '__main__':
    asyncio.run(test_worker_dpo())