import os
import re
import time
import subprocess

def bust_cache_and_deploy():
    print("\n================ [ 最終突破: キャッシュ・バスターと自動デプロイ ] ================")
    file_path = "frontend/index.html"
    
    if not os.path.exists(file_path):
        print(f"🚨 {file_path} が見つかりません。")
        return

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 今の時間のタイムスタンプを生成 (例: 1716974000)
    new_timestamp = str(int(time.time()))
    
    # 正規表現で古いタイムスタンプ (app_final.js?v=〇〇) を見つけて、新しいものに書き換える
    new_content = re.sub(r'app_final\.js\?v=\d+', f'app_final.js?v={new_timestamp}', content)
    
    if content == new_content:
        print("⚠️ app_final.js?v=〇〇 の記述が見つかりませんでした。")
        return

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(new_content)
        
    print(f"✅ index.html のタイムスタンプを最新 ({new_timestamp}) に更新しました！")
    print("🚀 続けて、Firebaseへ自動デプロイを実行します...")
    
    try:
        # Pythonから直接デプロイコマンドを叩く
        subprocess.run(["firebase", "deploy", "--only", "hosting"], check=True, shell=True)
        print("\n🎉 デプロイ完了！ ブラウザへの強制ダウンロード命令を発動しました。")
    except subprocess.CalledProcessError as e:
        print(f"\n🚨 デプロイ中にエラーが発生しました: {e}")

if __name__ == "__main__":
    bust_cache_and_deploy()
