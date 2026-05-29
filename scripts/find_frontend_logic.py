import os

def find_frontend_logic():
    print("\n================ [ フロントエンド調査: 『鑑定中』の描画ロジック特定 ] ================")
    target_dir = "frontend"
    search_term = "鑑定中"
    
    if not os.path.exists(target_dir):
        print(f"🚨 {target_dir} フォルダが見つかりません。")
        return

    found = False
    for root, dirs, files in os.walk(target_dir):
        for file in files:
            if file.endswith((".js", ".html")):
                path = os.path.join(root, file)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                        for i, line in enumerate(lines):
                            if search_term in line:
                                found = True
                                print(f"\n📁 該当ファイル: {path} (行番号: {i+1})")
                                print("-" * 60)
                                # 前後10行を抽出して表示
                                start = max(0, i - 10)
                                end = min(len(lines), i + 10)
                                for j in range(start, end):
                                    prefix = "👉 " if j == i else "   "
                                    print(f"{prefix}{j+1:4d}: {lines[j].rstrip()}")
                                print("-" * 60)
                except Exception as e:
                    print(f"  ⚠️ {path} の読み込みエラー: {e}")

    if not found:
        print("\n⚠️ '鑑定中' という文字列がフロントエンドのコードから見つかりませんでした。")

if __name__ == "__main__":
    find_frontend_logic()
