import subprocess
import sys

def main():
    print("="*60)
    print("🚀 [自動誘導] 正しいGCP要塞を特定し、VS Codeを強制接続します")
    print("="*60)
    
    # プロジェクトIDの取得
    proj_cmd = "gcloud config get-value project"
    proj_result = subprocess.run(proj_cmd, shell=True, text=True, capture_output=True)
    project_id = proj_result.stdout.strip()

    # 現在 RUNNING 状態のVMのゾーンを動的に取得
    print("🔍 稼働中の要塞の現在地（ゾーン）を探知中...")
    zone_cmd = 'gcloud compute instances list --filter="name=nazokake-l4-vm AND status=RUNNING" --format="value(zone)"'
    zone_result = subprocess.run(zone_cmd, shell=True, text=True, capture_output=True)
    zone = zone_result.stdout.strip()

    if not zone:
        print("🚨 稼働中の nazokake-l4-vm が見つかりません。GCPコンソールを確認してください。")
        sys.exit(1)

    # ターゲットホスト名の構築
    target_host = f"nazokake-l4-vm.{zone}.{project_id}"
    print(f"✅ 正しい接続先を特定しました: {target_host}")
    
    # VS Codeをリモート接続モードで強制起動
    print("\n🚪 新しいVS Codeウィンドウで要塞への扉を開きます...")
    print("※ 新しいウィンドウが開いたら、左下の青いマークが接続完了になるのをお待ちください。")
    launch_cmd = f"code --remote ssh-remote+{target_host}"
    subprocess.run(launch_cmd, shell=True)

if __name__ == "__main__":
    main()
