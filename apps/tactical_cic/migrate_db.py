import sqlite3
import os
from pathlib import Path

# プロジェクトのローカルDBを指定（必要に応じてファイル名を変更してください）
# プロジェクトルート基準の絶対パスで解決する(webhook_api.pyと同じ理由: cwdに依存すると
# 別cwdから実行した際に誤った空のDBファイルを新規生成してしまう)。
#
# 【instructions/225で判明】このファイル単体でCLI実行する場合のデフォルト値は
# parents[1](apps/tactical_cic/migrate_db.py基準で1階層上=apps/)だったが、
# webhook_api.pyはparents[2](リポジトリルート/コンテナの/app)を使っており、
# 両者が食い違うと「migrate_db.pyが作ったテーブルをwebhook_api.pyが見つけられない」
# バグになる(実際、webhook_api.pyからは呼び出されておらず未使用のまま放置されていた)。
# migrate_schema()にdb_pathを明示的に渡せるようにし、webhook_api.py側の
# 起動時自動マイグレーションでは常にwebhook_api.py自身が解決したDB_PATHを渡すことで、
# 2箇所の独立したパス計算が食い違う余地を無くす。
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = str(_PROJECT_ROOT / 'local_ssot.db')
if not os.path.exists(DB_PATH):
    # フォールバックとしてのファイル名
    DB_PATH = str(_PROJECT_ROOT / 'nazokake.db')

def migrate_schema(db_path: str = DB_PATH) -> None:
    print(f'Connecting to DB: {os.path.abspath(db_path)}')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Tactical CIC 専用テーブルの作成
    cursor.executescript('''
        CREATE TABLE IF NOT EXISTS tactical_missions (
            mission_id TEXT PRIMARY KEY,
            target_url TEXT NOT NULL,
            status TEXT NOT NULL,
            conflict_context JSON,
            coa_options JSON,
            preachiness_score REAL,
            selected_warhead TEXT,
            fired_at TIMESTAMP,
            bda_metrics JSON,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Anti-Hubris ③: Rate Limiting 用の複合インデックス
        CREATE INDEX IF NOT EXISTS idx_tactical_target_url_created
        ON tactical_missions(target_url, created_at DESC);
    ''')

    conn.commit()
    conn.close()
    print('✅ SQLite: tactical_missions テーブルと制約インデックスの構築が完了しました。')

# 後方互換のためのエイリアス(以前はmigrate_db()という関数名だった)。
migrate_db = migrate_schema

if __name__ == '__main__':
    migrate_schema()
