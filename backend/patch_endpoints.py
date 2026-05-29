import os
import re
import sys

def find_target_file(search_pattern: str) -> str | None:
    """
    指定されたパターンを含む関数定義を持つ最初のPythonファイルを見つける。
    仮想環境やキャッシュディレクトリはスキップする。
    """
    for root, _, files in os.walk("."):
        if ".venv" in root or "__pycache__" in root:
            continue
        for file in files:
            if file.endswith(".py"):
                path = os.path.join(root, file)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        content = f.read()
                        if search_pattern in content:
                            return path
                except UnicodeDecodeError:
                    # エンコーディングエラーが発生したファイルはスキップ
                    continue
                except IOError:
                    # その他のIOエラーをスキップ
                    continue
    return None

def optimize_file_content(file_path: str) -> str:
    """
    指定されたファイルの内容を、非同期処理の修正と引数クリーンアップを行う。
    """
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. BackgroundTasks 引数を削除
    # 複数のパターンをまとめて処理することで効率化を図る
    content = re.sub(r",\s*background_tasks:\s*BackgroundTasks", "", content)
    content = re.sub(r"background_tasks:\s*BackgroundTasks\s*,?", "", content)

    # 2. background_tasks.add_task を直接実行（冬眠させない処理）に変換
    # ターゲット: background_tasks.add_task(task_name, *args)
    # 置換後のロジック: await task_name(*args) if is_coroutine else task_name(*args)
    replacement = r"await \1(\2) if __import__('asyncio').iscoroutinefunction(\1) else \1(\2)"
    
    # 正規表現のキャプチャグループ: 1=タスク名, 2=引数リスト
    content = re.sub(
        r"background_tasks\.add_task\(\s*([a-zA-Z0-9_]+)\s*,\s*(.*?)\)",
        replacement,
        content
    )
    return content

if __name__ == "__main__":
    SEARCH_PATTERN = "def submit_human_nazokake"
    
    target_file = find_target_file(SEARCH_PATTERN)

    if not target_file:
        sys.exit(1)

    try:
        optimized_content = optimize_file_content(target_file)
    except Exception as e:
        sys.exit(f"ファイル処理中にエラーが発生しました: {e}")

    try:
        with open(target_file, "w", encoding="utf-8") as f:
            f.write(optimized_content)
    except IOError as e:
        sys.exit(f"ファイル書き込み中にエラーが発生しました: {e}")
    
    # 成功した場合は、何も出力しない（純粋なテキストのみのルールに従うため）
    pass