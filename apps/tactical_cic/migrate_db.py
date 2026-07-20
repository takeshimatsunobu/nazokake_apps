import sqlite3
import os
from pathlib import Path

# プロジェクトのローカルDBを指定（必要に応じてファイル名を変更してください）
# プロジェクトルート基準の絶対パスで解決する(webhook_api.pyと同じ理由: cwdに依存すると
# 別cwdから実行した際に誤った空のDBファイルを新規生成してしまう)。
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = str(_PROJECT_ROOT / 'local_ssot.db')
if not os.path.exists(DB_PATH):
    # フォールバックとしてのファイル名
    DB_PATH = str(_PROJECT_ROOT / 'nazokake.db')

def migrate_db():
    print(f'Connecting to DB: {os.path.abspath(DB_PATH)}')
    conn = sqlite3.connect(DB_PATH)
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

if __name__ == '__main__':
    migrate_db()
