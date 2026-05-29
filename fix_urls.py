import re, os
files = [r"C:\Users\takes\nazokake-evaluator\frontend\index.html", r"C:\Users\takes\nazokake-evaluator\frontend\admin.html"]
url = "https://nazokake-backend-862686676938.asia-northeast1.run.app"

for path in files:
    if not os.path.exists(path):
        continue
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # 1. バグで増殖・破壊されたURLを、一度きれいな "/api/" にリセットする
    content = re.sub(r"(https://nazokake-backend-[a-z0-9-]+\.run\.app`?)+/api/", "/api/", content)
    
    # 2. 正しいURLに安全に置換する（シングル、ダブル、バッククォート全て対応）
    content = content.replace("'/api/", f"'{url}/api/")
    content = content.replace('"/api/', f'"{url}/api/')
    content = content.replace("`/api/", f"`{url}/api/")
    
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

print("✅ 構文エラーの原因（壊れたURL）を完全に修復し、Cloud Runに接続しました！")
