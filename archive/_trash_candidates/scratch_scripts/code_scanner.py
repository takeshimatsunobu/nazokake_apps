import os
import sys
import logging
from pathlib import Path

# ロギングの初期化 (DLQ/監査ログの代替として標準エラーへ明確に出力)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# SSoTで定義された重要パスと除外リスト
CORE_PATHS = [Path("apps/evaluator"), Path("apps/batch_factory")]
EXCLUDE_DIRS = {".venv", "__pycache__", ".git", "node_modules", ".tox"}

def verify_core_paths(root_dir: Path):
    """
    SSoTに定義されたコアパスが存在し、アクセス可能か検証する。
    Fail-Closed: 問題があれば即座に例外を送出し、プロセスを強制停止する。
    """
    for core_path in CORE_PATHS:
        target = root_dir / core_path
        if not target.exists():
            logger.critical(f"SSoT違反: コアディレクトリが見つかりません: {target}")
            raise FileNotFoundError(f"SSoT Core path missing: {target}")
        if not os.access(target, os.R_OK):
            logger.critical(f"SSoT違反: コアディレクトリへのアクセス権限がありません: {target}")
            raise PermissionError(f"Permission denied for SSoT Core path: {target}")

def scan_codebase(root_dir: Path):
    """
    仮想環境等を明示的に枝刈り(Prune)しながらファイルを厳格にトラバーサルする。
    ハック（正規表現での強引なパス除外等）は使用しない。
    """
    verify_core_paths(root_dir)
    scanned_files = []

    for path in root_dir.rglob("*"):
        # 探索ツリーからの明示的な枝刈り
        if any(part in EXCLUDE_DIRS for part in path.parts):
            continue
        
        if path.is_file() and path.suffix == ".py":
            scanned_files.append(path)
    
    return scanned_files

if __name__ == "__main__":
    try:
        root = Path(".").resolve()
        files = scan_codebase(root)
        logger.info(f"SSoT監査完了: {len(files)} 個のPythonファイルを検出しました。")
        # 将来的にここで正式な監査レポートJSONを出力する
    except Exception as e:
        logger.critical(f"Fail-Closed: 致命的なエラーにより監査プロセスを強制停止します: {e}")
        sys.exit(1)
