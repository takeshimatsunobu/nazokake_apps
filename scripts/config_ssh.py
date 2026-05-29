import subprocess
import sys

def main():
    print("="*60)
    print("🔌 [フェーズ0 - Step 2] VS Code Remote-SSH 接続設定の自動化")
    print("="*60)
    
    print("🔄 gcloud に SSH 鍵の自動生成と config ファイルの更新を依頼しています...")
    # プロジェクトIDを取得して確実に指定する
    project_id = subprocess.run("gcloud config get-value project", shell=True, text=True, capture_output=True).stdout.strip()
    
    cmd = f"gcloud compute config-ssh --project={project_id} --quiet"
    result = subprocess.run(cmd, shell=True, text=True, capture_output=True)
    
    if result.returncode != 0:
        print(f"🚨 SSH設定の自動化に失敗しました:\n{result.stderr}")
        sys.exit(1)
        
    print("✅ SSH設定ファイル (~/.ssh/config) の更新が完了しました！\n")
    print("👇 VS Codeで以下の手順を実行してください:")
    print("  1. 左下の青い「><」マーク（リモートウィンドウを開く）をクリック")
    print("  2. 「Connect to Host... (ホストに接続...)」を選択")
    print("  3. 以下のホスト名を選択（または入力）してEnter")
    print(f"\n     ▶️  nazokake-l4-vm.us-east1-b.{project_id}  ◀️\n")
    print("※ 初回接続時はプラットフォームに「Linux」を選択し、指紋認証（fingerprint）に「Continue」と答えてください。")

if __name__ == "__main__":
    main()
