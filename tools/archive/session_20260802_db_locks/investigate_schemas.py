Set-Content -Path "tools/investigate_schemas.py" -Value @"
import ast
import json
from pathlib import Path

def inspect_schemas():
target_paths = [
Path('packages/shared_core/nazokake_core/schemas.py'),
Path('llm/schemas.py'),
Path('apps/evaluator/backend/models/schemas.py')
]

valid_path = None
for p in target_paths:
    if p.exists():
        valid_path = p
        break
        
if not valid_path:
    print(json.dumps({'error': 'スキーマ定義ファイルが見つかりません。'}))
    return

with open(valid_path, 'r', encoding='utf-8') as f:
    source = f.read()

tree = ast.parse(source)
classes_info = []

for node in ast.walk(tree):
    if isinstance(node, ast.ClassDef):
        class_data = {
            'name': node.name,
            'bases': [b.id for b in node.bases if isinstance(b, ast.Name)],
            'fields': []
        }
        for body_node in node.body:
            if isinstance(body_node, ast.AnnAssign) and isinstance(body_node.target, ast.Name):
                if isinstance(body_node.annotation, ast.Name):
                    field_type = body_node.annotation.id
                elif isinstance(body_node.annotation, ast.Subscript):
                    field_type = 'Subscript (Generic)'
                else:
                    field_type = 'Complex Type'
                class_data['fields'].append({'name': body_node.target.id, 'type': field_type})
        classes_info.append(class_data)

result = {
    'target_file': str(valid_path),
    'classes': classes_info
}
print(json.dumps(result, indent=2, ensure_ascii=False))
if name == 'main':
inspect_schemas()
"@ -Encoding UTF8