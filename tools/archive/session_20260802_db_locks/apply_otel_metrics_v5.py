import libcst as cst
import subprocess
TARGET_FILE = "packages/shared_core/nazokake_core/database.py"
class OTelInjector(cst.CSTTransformer):
 def leave_Module(self, original_node, updated_node):
  import_node = cst.parse_statement("from opentelemetry import metrics\n")
  
  globals_code = "\n".join([
   "meter = metrics.get_meter('nazokake_core.database')",
   "db_retry_counter = meter.create_counter('db.retry.count', description='Number of database retries due to locks')",
   "",
   "def _on_db_retry(retry_state):",
   " db_retry_counter.add(1, {'attempt_number': retry_state.attempt_number})",
   " before_sleep_log(logger, logging.WARNING)(retry_state)",
   ""
  ])
  globals_nodes = cst.parse_module(globals_code).body
  
  insert_idx = 0
  for i, node in enumerate(updated_node.body):
   if isinstance(node, cst.SimpleStatementLine):
    stmt = node.body[0]
    if isinstance(stmt, cst.Assign) and len(stmt.targets) == 1:
     if getattr(stmt.targets[0].target, "value", "") == "logger":
      insert_idx = i + 1
      break
  
  import_idx = 0
  for i, node in enumerate(updated_node.body):
   if isinstance(node, cst.SimpleStatementLine) and isinstance(node.body[0], (cst.Import, cst.ImportFrom)):
    import_idx = i + 1
    break
  
  new_body = list(updated_node.body)
  for g_node in reversed(globals_nodes):
   new_body.insert(insert_idx, g_node)
  new_body.insert(import_idx, import_node)
  
  return updated_node.with_changes(body=new_body)
 def leave_Call(self, original_node, updated_node):
  if isinstance(original_node.func, cst.Name) and original_node.func.value == "retry":
   new_args = []
   for arg in updated_node.args:
    if arg.keyword and arg.keyword.value == "before_sleep":
     new_args.append(arg.with_changes(value=cst.Name("_on_db_retry")))
    else:
     new_args.append(arg)
   return updated_node.with_changes(args=new_args)
  return updated_node
def main():
 with open(TARGET_FILE, "r", encoding="utf-8") as f:
  tree = cst.parse_module(f.read())
 
 modified_tree = tree.visit(OTelInjector())
 
 with open(TARGET_FILE, "w", encoding="utf-8") as f:
  f.write(modified_tree.code)
 
 print("Successfully injected OpenTelemetry metrics.")
 subprocess.run(["uv", "run", "ruff", "check", "--select", "I", "--fix", TARGET_FILE], check=False)
 subprocess.run(["uv", "run", "ruff", "format", TARGET_FILE], check=False)
 subprocess.run(["git", "add", TARGET_FILE], check=True)
 subprocess.run(["git", "commit", "-m", "feat(db): instrument database retry with OpenTelemetry metrics"], check=True)
 print("Commit successful.")
main()
