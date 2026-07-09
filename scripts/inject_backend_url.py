import subprocess
import re
from pathlib import Path

PROJECT_ID = "nazokakeapp-137e5"
SERVICE_NAME = "nazokake-backend"

print(f"🔍 [Phase 1] Cloud Run（{SERVICE_NAME}）の本番URLを自動探査中...")
try:
    # gcloudコマンドでCloud RunのURLを直接取得
    res = subprocess.run(
        ["gcloud", "run", "services", "list", "--project", PROJECT_ID, "--filter", f"metadata.name={SERVICE_NAME}", "--format", "value(status.url)"],
        capture_output=True, text=True, check=True
    )
    backend_url = res.stdout.strip()
    
    if not backend_url:
        print(f"⚠️ Cloud Run上に '{SERVICE_NAME}' が見つかりません。")
        print("💡 バックエンドがまだデプロイされていないか、プロジェクトIDが異なる可能性があります。")
    else:
        print(f"✅ バックエンドURLを確保: {backend_url}")
        
        js_path = Path("frontend/app_final.js")
        if js_path.exists():
            text = js_path.read_text(encoding="utf-8")
            # 前回のバッチで入れた仮置きURLを、取得した本番URLに書き換え
            text = re.sub(r'const CLOUD_RUN_URL = "[^"]+";', f'const CLOUD_RUN_URL = "{backend_url}";', text)
            js_path.write_text(text, encoding="utf-8")
            print("✅ app_final.js に本番バックエンドURLの注入が完了しました！")
            
        print("\n🚀 [Phase 2] Firebase Hostingへの本番デプロイ準備が完了しました！")
        print("   ターミナルで以下のコマンドを実行し、フロントエンドを世界に公開してください:")
        print("   firebase deploy --only hosting")

except Exception as e:
    print(f"🚨 エラー発生: gcloudコマンドが実行できないか、GCPの認証が切れています。\n詳細: {e}")
