import libcst as cst
from pathlib import Path
import subprocess

# 先ほど抽出していただいた正確な元のシグネチャと依存関係を100%踏襲した新しい関数
new_func_code = """
async def _process_job(db, collection: str, job: dict[str, Any]) -> None:
    import asyncio
    import json
    import sys
    import traceback
    from pathlib import Path

    doc_id = job['doc_id']
    odai = job['odai']
    retry_count = job['retry_count']
    dpo_pair_id = job.get('dpo_pair_id')

    if not odai:
        _log(f'⚠️ [{doc_id}] odaiが空のため生成をスキップし、失敗として扱います。')
        await _mark_failure(db, collection, doc_id, odai, dpo_pair_id, retry_count, 'odai is empty')
        return

    N = 3
    sem = asyncio.Semaphore(3)

    async def _bounded_gen_and_eval(idx):
        async with sem:
            raw_result = await generate_via_llmjp(odai)
            text = _compose_text(odai, raw_result)
            evaluation = await run_evaluation(odai, text)
            return {
                'idx': idx,
                'raw_result': raw_result,
                'text': text,
                'evaluation': evaluation,
                's_total': evaluation.get('s_total', 0)
            }

    try:
        evaluated_candidates = await asyncio.gather(*[_bounded_gen_and_eval(i) for i in range(N)])
    except Exception as e:
        _log(f'⚠️ [{doc_id}] ELYZA生成/評価に失敗: {e}')
        traceback.print_exc(file=sys.stderr)
        await _mark_failure(db, collection, doc_id, odai, dpo_pair_id, retry_count, str(e))
        return

    best_candidate = max(evaluated_candidates, key=lambda x: x['s_total'])

    try:
        log_dir = Path('run/audit_reports')
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / 'dpo_preference_log.jsonl'
        with open(log_file, 'a', encoding='utf-8') as f:
            for cand in evaluated_candidates:
                cand_dict = cand.copy()
                cand_dict['is_chosen'] = (cand['idx'] == best_candidate['idx'])
                cand_dict['doc_id'] = doc_id
                cand_dict['dpo_pair_id'] = dpo_pair_id
                f.write(json.dumps(cand_dict, ensure_ascii=False) + chr(10))
    except Exception as e:
        _log(f'⚠️ [{doc_id}] DPOログ書き出しに失敗: {e}')

    raw_result = best_candidate['raw_result']
    text = best_candidate['text']
    evaluation = best_candidate['evaluation']

    fields = {
        'result_llmjp': raw_result,
        'nazokake_text_llmjp': text,
        'scores_llmjp': evaluation['scores'],
        's_total_llmjp': evaluation['s_total'],
        'overall_llmjp': evaluation['overall'],
        'axis_comments_llmjp': evaluation['axis_comments'],
        'llmjp_status': 'completed',
        'elyza_job_status': 'completed',
        'elyza_job_locked_at': None,
        'elyza_job_retry_count': 0
    }
    await _mark_job_outcome(db, collection, doc_id, odai, local_fields={**fields, 'dpo_pair_id': dpo_pair_id}, scoped_fields=fields)
    _log(f'✅ [{doc_id}] ELYZA生成・評価・Firestore書き戻しが完了しました。')
"""

parsed_func = cst.parse_module(new_func_code).body[0]

class WorkerTransformer(cst.CSTTransformer):
    def leave_FunctionDef(self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef) -> cst.FunctionDef:
        if original_node.name.value == "_process_job":
            return parsed_func
        return updated_node

def apply_patch():
    worker_path = Path("workers/ondemand_elyza_worker.py")
    if not worker_path.exists():
        print(f"Error: {worker_path.absolute()} not found. ディレクトリを確認してください。")
        return

    try:
        source = worker_path.read_text(encoding="utf-8")
        tree = cst.parse_module(source)
        modified_tree = tree.visit(WorkerTransformer())
        worker_path.write_text(modified_tree.code, encoding="utf-8")

        print(f"[OK] Patched: {worker_path}")
        subprocess.run(["git", "add", str(worker_path)], check=True)
        subprocess.run(["git", "commit", "-m", "refactor(worker): implement Best-of-N with Semaphore and DPO logging"], check=True)
        result = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True)
        print(f"[OK] Git commit completed successfully. Hash: {result.stdout.strip()}")
    except Exception as e:
        print(f"Error occurred: {e}")

if __name__ == "__main__":
    apply_patch()