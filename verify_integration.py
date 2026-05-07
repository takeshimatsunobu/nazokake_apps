import os

def verify_monorepo():
    print("🔍 統合ディレクトリ構造の検証を開始します...\n")

    # プロジェクトとして必須のディレクトリとファイルの定義
    expected_structure = {
        "backend-worker": [
            "gemini_api.py",
            "firestore_db.py",
            "requirements.txt"
        ],
        "frontend-ui": [
            "app.py",
            "db_client.py",
            "ranking_calc.py",
            "requirements.txt"
        ]
    }

    all_passed = True
    base_dir = os.getcwd()

    print(f"📂 現在の実行ディレクトリ: {base_dir}\n")

    for folder, files in expected_structure.items():
        if not os.path.exists(folder):
            print(f"❌ フォルダが見つかりません: {folder}/")
            all_passed = False
            continue
        
        print(f"✅ フォルダを確認: {folder}/")
        for file in files:
            file_path = os.path.join(folder, file)
            if os.path.exists(file_path):
                print(f"  ├── ✅ {file}")
            else:
                print(f"  ├── ❌ ファイル欠損: {file}")
                all_passed = False

    print("\n========================================")
    if all_passed:
        print("🎉 統合成功！モノレポ構成（backend-worker / frontend-ui）が正しく構築されています。")
    else:
        print("⚠️ 統合に不備があります。× がついているファイルの移動やコピーが漏れていないか確認してください。")
    print("========================================")

if __name__ == "__main__":
    verify_monorepo()
