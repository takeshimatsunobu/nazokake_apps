import json
import re
from pathlib import Path
facts = json.loads(Path('run/architecture_facts.json').read_text('utf-8'))
actual = {d.replace('\\', '/') + '/' + f for d, fs in facts.items() for f in fs}
ssot_txt = Path('SSoT_architecture.md').read_text('utf-8')
doc_paths = set(re.findall(r'(?:apps|tools|workers|packages|infra|run)/(?:[a-zA-Z0-9_-]+/)*[a-zA-Z0-9_-]+\.[a-z0-9]+', ssot_txt))
report = ['# SSoT Audit Report\n\n## 1. Missing in Codebase']
report.extend(f'- [ ] `{p}`' for p in sorted(doc_paths - actual))
report.append('\n## 2. Undocumented')
report.extend(f'- [ ] `{p}`' for p in sorted(actual - doc_paths) if '.pyc' not in p and '__' not in p)
report.append('\n## 3. Canonical Naming Map\n| Path | Name |\n|---|---|')
report.extend(f'| `{p}` | {Path(p).stem.replace("_", " ").title()} |' for p in sorted(actual) if p.endswith('.py') and '__' not in p)
Path('run/ssot_audit_report.md').write_text('\n'.join(report), 'utf-8')
print('Done! Open run/ssot_audit_report.md in VSCode.')