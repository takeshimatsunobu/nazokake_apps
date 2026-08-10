import libcst as cst
from pathlib import Path
import subprocess

patch_body = '''
async def _process_job(self, job_id, odai):
    import asyncio
    import json
    from pathlib import Path

    N = 3
    sem = asyncio.Semaphore(3)

    async def _bounded_gen_and_eval(idx):
        async with sem:
            candidate = await self._generate_candidate(odai)
            evaluated = await self._evaluate_candidate(candidate)
            return evaluated

    evaluated_candidates = await asyncio.gather(*[_bounded_gen_and_eval(i) for i in range(N)])

    best_candidate = max(
        evaluated_candidates,
        key=lambda x: x.s_total if hasattr(x, "s_total") else (x.get("s_total", 0) if isonstance(x, dict) else 0)
    )

    log_dir = Path("run/audit_reports")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "dpo_preference_log.jsonl"

    with open(log_file, "a", encoding="utf-8") as f:
        for cand in evaluated_candidates:
            cand_dict = cand.__dict__.copy() if hasattr(cand, "__dict__") else (dict(cand) if isinstance(cand, dict) else {"data": str(cand)})
            cand_dict["is_chosen"] = (cand == best_candidate)
            cand_dict["job_id"] = job_id
            f.write(json.dumps(cand_dict, ensure_ascii=False) + "\n")

    await self._mark_job_outcome(job_id, best_candidate)
'''

parsed_dummy = cst.parse_module(patch_body).body[0].body

class WorkerTransformer(cst.CSTTransformer):
    def leave_AsyncFunctionDef(self, original_node: cst.AsyncFunctionDef, updated_node: cst.AsyncFunctionDef) -> cst.AsyncFunctionDef:
        if original_node.name.value == "_process_job":
            return updated_node.with_changes(body=parsed_dummy)
        return updated_node

def apply_patch():
    worker_path = Path("workers/ondemand_elyza_worker.py")
    if not worker_path.exists():
        print(f"Error: {worker_path} not found.")
        return

    try:
        source = worker_path.read_text(encoding="utf-8")
        tree = cst.parse_module(source)
        modified_tree = tree.visit(WorkerTransformer())
        worker_path.write_text(modified_tree.code, encoding="utf-8")
        
        print(f"‍ Patched: {worker_path}")
        print("‍ 制隡: asyncio.Semaphore(3) を導入しました.")
        print("‍ ロも: run/audit_reports/dpo_preference_log.jsonl への敗退データ出力を実装しました.")
        print("‍ ロック: Best 1のみを_mark_job_outcomeでアトミックにUPSERTするよう変更しました.")
        
        subprocess.run(["git", "add", str(worker_path)], check=True)
        subprocess.run(["git", "commit", "-m", "refactor(worker): implement Best-of-N with Semaphore and DPO logging"], check=True)
        
        result = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True)
        print(f"‍ Git commit completed successfully. Hash: {result.stdout.strip()}")
    except Exception as e:
        print(f"Error occurred: {e}")

if __name__ == "__main__":
    apply_patch()