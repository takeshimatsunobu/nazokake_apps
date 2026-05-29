import os

def patch_frontend():
    print("\n================ [ フロントエンド改修: 変数名のすり合わせパッチ ] ================")
    file_path = "frontend/app_final.js"
    
    if not os.path.exists(file_path):
        print(f"🚨 {file_path} が見つかりません。")
        return

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 修正前の文字列がファイル内に存在するか確認
    target1 = 'const scoreText = data.s_total ? data.s_total.toFixed(2) : "鑑定中";'
    target2 = 'const aiScore = item.s_total ? item.s_total.toFixed(2) : "鑑定中";'
    
    if target1 not in content or target2 not in content:
        print("⚠️ 修正対象のコードが見つかりません。既に修正済みか、コードが変更されています。")
        return

    # 💡 修正の核心： total_score と s_total の両方に対応させる
    content = content.replace(
        target1,
        'const scoreText = (data.total_score || data.s_total) ? (data.total_score || data.s_total).toFixed(2) : "鑑定中";'
    )
    
    content = content.replace(
        target2,
        'const aiScore = (item.total_score || item.s_total) ? (item.total_score || item.s_total).toFixed(2) : "鑑定中";'
    )

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
        
    print("✅ frontend/app_final.js の修正が完了しました！")
    print("✨ これでフロントエンドが新しい 'total_score' を認識できるようになります。")

if __name__ == "__main__":
    patch_frontend()
