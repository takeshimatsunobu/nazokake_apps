import os
import shutil
import logging
import subprocess
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

CACHE_DIR = Path(".cache/testmon").resolve()
TESTMON_DATA_FILE = ".testmondata"

class WorktreeManager:
    """
    SSoT準拠: セキュリティ隔離とキャッシュ永続化を両立するワークツリーマネージャー。
    """
    def __init__(self, branch_name: str, worktree_path: Path):
        self.branch_name = branch_name
        self.worktree_path = worktree_path.resolve()
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def setup_worktree(self):
        """ワークツリーを作成し、永続化レイヤーからテストキャッシュを復元する"""
        logger.info(f"ワークツリーをセットアップします: {self.worktree_path}")
        try:
            # git worktree add の実行 (エラー時は例外送出)
            subprocess.run(
                ["git", "worktree", "add", str(self.worktree_path), self.branch_name],
                check=True, capture_output=True, text=True
            )
            
            # キャッシュの復元 (存在する場合のみ)
            cached_file = CACHE_DIR / TESTMON_DATA_FILE
            target_file = self.worktree_path / TESTMON_DATA_FILE
            
            if cached_file.exists():
                shutil.copy2(cached_file, target_file)
                logger.info("pytest-testmon のキャッシュデータを復元しました。")
                
        except subprocess.CalledProcessError as e:
            logger.critical(f"ワークツリーの作成に失敗しました: {e.stderr}")
            raise
        except Exception as e:
            logger.critical(f"セットアップ中に致命的なエラーが発生しました: {e}")
            raise

    def teardown_worktree(self):
        """
        ワークツリーを破棄する前に、更新されたテストキャッシュを安全に退避する。
        Fail-Closed: 退避中のI/Oエラーは握り潰さず伝播させる。
        """
        logger.info(f"ワークツリーのティアダウンを開始します: {self.worktree_path}")
        try:
            target_file = self.worktree_path / TESTMON_DATA_FILE
            cached_file = CACHE_DIR / TESTMON_DATA_FILE
            
            # キャッシュの退避（隔離環境から永続化レイヤーへ）
            if target_file.exists():
                shutil.copy2(target_file, cached_file)
                logger.info("pytest-testmon の最新キャッシュデータを永続化レイヤーへ退避しました。")
            else:
                logger.warning(f"退避すべき {TESTMON_DATA_FILE} が見つかりませんでした。全テストが実行されたか、テストがスキップされた可能性があります。")
                
            # 物理ディレクトリの破棄
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(self.worktree_path)],
                check=True, capture_output=True, text=True
            )
            logger.info("ワークツリーを安全に破棄しました。")
            
        except subprocess.CalledProcessError as e:
            logger.critical(f"ワークツリーの破棄に失敗しました: {e.stderr}")
            raise
        except OSError as e:
            logger.critical(f"キャッシュ退避中にI/Oエラーが発生しました。データ保護のためプロセスを停止します: {e}")
            raise
        except Exception as e:
            logger.critical(f"ティアダウン中に予期せぬエラーが発生しました: {e}")
            raise

if __name__ == "__main__":
    # 簡易動作テスト（本番ではインポートされて使用される）
    pass
