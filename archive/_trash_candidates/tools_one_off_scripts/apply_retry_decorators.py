import libcst as cst
import subprocess

TARGET_FILE = "packages/shared_core/nazokake_core/database.py"
TARGET_FUNCS = {
    "init_db", "upsert_item", "claim_pending_trend", "mark_trend_completed",
    "mark_synced", "mark_sync_failed", "append_audit_log",
    "async_bulk_restore_items_if_missing", "async_retry_dlq_item",
    "async_discard_dlq_item", "async_append_human_evaluation",
    "async_mark_trained", "async_try_claim_trigger_slot",
    "async_release_trigger_slot", "_record_evaluation_score_event",
    "_record_pipeline_outcome_event"
}

class RetryDecoratorAdder(cst.CSTTransformer):
    def __init__(self):
        self.retry_def = None

    def leave_FunctionDef(self, original_node, updated_node):
        # Extract with_db_retry definition to move it to the top
        if original_node.name.value == "with_db_retry":
            self.retry_def = updated_node
            return cst.RemoveFromParent()
        return updated_node

    def leave_AsyncFunctionDef(self, original_node, updated_node):
        if original_node.name.value in TARGET_FUNCS:
            for dec in original_node.decorators:
                if isinstance(dec.decorator, cst.Call) and getattr(dec.decorator.func, "value", "") == "with_db_retry":
                    return updated_node
            new_decorator = cst.Decorator(decorator=cst.Call(func=cst.Name("with_db_retry"), args=[]))
            return updated_node.with_changes(decorators=(new_decorator,) + updated_node.decorators)
        return updated_node

    def leave_Module(self, original_node, updated_node):
        if self.retry_def:
            # Find the index to insert (after imports)
            insert_idx = 0
            for i, node in enumerate(updated_node.body):
                if isinstance(node, cst.SimpleStatementLine) and isinstance(node.body[0], (cst.Import, cst.ImportFrom)):
                    insert_idx = i + 1
            
            new_body = list(updated_node.body)
            new_body.insert(insert_idx, self.retry_def)
            return updated_node.with_changes(body=new_body)
        return updated_node

def main():
    with open(TARGET_FILE, "r", encoding="utf-8") as f:
        tree = cst.parse_module(f.read())
    
    transformer = RetryDecoratorAdder()
    modified_tree = tree.visit(transformer)
    
    with open(TARGET_FILE, "w", encoding="utf-8") as f:
        f.write(modified_tree.code)
        
    print("Successfully moved with_db_retry and added decorators.")
    subprocess.run(["uv", "run", "ruff", "check", "--select", "I", "--fix", TARGET_FILE], check=False)
    subprocess.run(["uv", "run", "ruff", "format", TARGET_FILE], check=False)
    subprocess.run(["git", "add", TARGET_FILE, __file__], check=True)
    subprocess.run(["git", "commit", "-m", "fix(db): apply @with_db_retry decorator and fix definition order"], check=True)
    print("Commit successful.")

if __name__ == "__main__":
    main()