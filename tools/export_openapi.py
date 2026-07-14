"""
tools/export_openapi.py
========================
apps/evaluator/backend の FastAPIアプリケーションインスタンスを直接importし、
app.openapi() の結果を apps/evaluator/frontend/openapi.json へ静的にダンプする。

main.py は core/api をバックエンドディレクトリ相対のトップレベルパッケージとして
importしているため(apps.evaluator.backend.main のような素のドット付きimportは
成立しない)、run_api.ps1 の uvicorn起動と同じ回避策(cwdをbackendディレクトリへ
切り替えてからimportする)を踏襲する。ローカルサーバー(uvicorn)は起動しない。

使い方:
    .venv\\Scripts\\python.exe tools\\export_openapi.py
"""

import json
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "apps" / "evaluator" / "backend"
OUTPUT_PATH = PROJECT_ROOT / "apps" / "evaluator" / "frontend" / "openapi.json"


def main() -> int:
    if not BACKEND_DIR.is_dir():
        print(f"❌ バックエンドディレクトリが見つかりません: {BACKEND_DIR}")
        return 1

    # main.py が `core`/`api` をトップレベルパッケージとしてimportするため、
    # backendディレクトリ自体をsys.pathへ追加する必要がある。
    sys.path.insert(0, str(BACKEND_DIR))
    import os

    original_cwd = Path.cwd()
    os.chdir(BACKEND_DIR)
    try:
        import main as backend_main  # noqa: E402
        spec = backend_main.app.openapi()
    finally:
        os.chdir(original_cwd)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"✅ OpenAPIスキーマをダンプしました: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
