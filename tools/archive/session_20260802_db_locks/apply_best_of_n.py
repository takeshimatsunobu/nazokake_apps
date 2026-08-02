import libcst as cst
from pathlib import Path
import subprocess

target = Path("workers/ondemand_elyza_worker.py")
src = target.read_text(encoding="utf-8")

new_func = cst.parse_statement('''async def _process_job(db, collection: str, job: dict[str, Any]) -> None:
    doc_id = job['doc_id']
    odai = job['odai']
    retry_count = job['retry_count']
    dpo_pair_id = job.get('dpo_pair_id')
    if not odai:
        _log(f'[{doc_id}] odai is empty. skipping.')
        await _mark_failure(db, collection, doc_id, odai, dpo_pair_id, retry_count, 'odai empty')
        return

    async def _gen(i: int):
        try:
            raw = await generate_via_llmjp(odai)
            txt = _compose_text(odai, raw)
            ev = await run_evaluation(odai, txt)
            return {"raw": raw, "txt": txt, "ev": ev, "err": None}
        except Exception as e:
            return {"raw": None, "txt": None, "ev": None, "err": str(e)}

    import asyncio
    N = 3
    _log(f'[{doc_id}] Starting Best-of-{N} (odai={odai})')
    tasks = [_gen(i) for i in range(N)]
    res = await asyncio.gather(*tasks)

    valid = [r for r in res if r["err"] is None]
    if not valid:
        err_msg = "All failed: " + ", ".join([r["err"] for r in res])
        _log(f'[{doc_id}] failed: {err_msg}')
        await _mark_failure(db, collection, doc_id, odai, dpo_pair_id, retry_count, err_msg)
        return

    best = max(valid, key=lambda r: r["ev"]["s_total"])
    fields = {
        'result_llmjp': best["raw"], 
        'nazokake_text_llmjp': best["txt"], 
        'scores_llmjp': best["ev"]['scores'], 
        's_total_llmjp': best["ev"]['s_total'], 
        'overall_llmjp': best["ev"]['overall'], 
        'axis_comments_llmjp': best["ev"]['axis_comments'], 
        'llmjp_status': 'completed', 
        'elyza_job_status': 'completed', 
        'elyza_job_locked_at': None, 
        'elyza_job_retry_count': 0
    }
    await _mark_job_outcome(db, collection, doc_id, odai, local_fields={**fields, 'dpo_pair_id': dpo_pair_id}, scoped_fields=fields)
    _log(f'[{doc_id}] Best-of-{N} done. (score: {best["ev"]["s_total"]})')
''')

class Replacer(cst.CSTTransformer):
    def __init__(self):
        self.done = False
    def leave_FunctionDef(self, node: cst.FunctionDef, updated_node: cst.FunctionDef) -> cst.CSTNode:
        if node.name.value == "_process_job":
            self.done = True
            return new_func
        return updated_node

module = cst.parse_module(src)
transformer = Replacer()
new_module = module.visit(transformer)

if transformer.done:
    target.write_text(new_module.code, encoding="utf-8")
    print("Success: _process_job updated to Best-of-N.")
    subprocess.run(["git", "add", str(target)], check=True)
    subprocess.run(["git", "commit", "-m", "feat(workers): implement Best-of-N generation for ELYZA"], check=True)
else:
    print("Error: _process_job not found.")