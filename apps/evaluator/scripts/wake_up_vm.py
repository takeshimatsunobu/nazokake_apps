import subprocess
import sys
import time

def run_cmd(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)

def main():
    print("="*60)
    print("☀️ GCP要塞を確実に叩き起こす（IP自動追従版）")
    print("="*60)
    
    # プロジェクトIDとゾーンの取得
    proj = run_cmd("gcloud config get-value project").stdout.strip()
    zone = run_cmd('gcloud compute instances list --filter="name=nazokake-l4-vm" --format="value(zone)"').stdout.strip()

    if not zone:
        print("🚨 VMが見つかりません。GCPコンソールを確認してください。")
        sys.exit(1)

    print(f"📍 要塞を発見 (Zone: {zone})。起動コマンドを送信します...")
    run_cmd(f"gcloud compute instances start nazokake-l4-vm --zone={zone} --project={proj} --quiet")

    print("⏳ OSとSSHサーバーの完全起動を待機中 (30秒)...")
    for i in range(30, 0, -5):
        print(f"   ... 残り {i} 秒")
        time.sleep(5)

    print("🔄 変更された外部IPアドレスを検知し、VS Codeの接続設定 (~/.ssh/config) を更新します...")
    res = run_cmd(f"gcloud compute config-ssh --project={proj} --quiet")
    if res.returncode != 0:
        print(f"🚨 SSH設定の更新に失敗しました:\n{res.stderr}")
        sys.exit(1)
        
    print("✅ 設定更新完了！")

    target_host = f"nazokake-l4-vm.{zone}.{proj}"
    print(f"\n🚪 新しいVS Codeウィンドウで要塞への扉を開きます: {target_host}")
    subprocess.run(f"code --remote ssh-remote+{target_host}", shell=True)

if __name__ == "__main__":
    main()
