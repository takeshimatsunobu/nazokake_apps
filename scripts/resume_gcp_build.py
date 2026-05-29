import os
import subprocess
import sys
import time

def main():
    print("="*60)
    print("🧹 [フェーズ1] 過去の遺物（TERMINATED VM）のクリーンアップ")
    print("="*60)
    
    project_id_cmd = "gcloud config get-value project"
    project_id = subprocess.run(project_id_cmd, shell=True, text=True, capture_output=True).stdout.strip()
    
    # us-west1-a の古いVMを強制削除
    print("🗑️ us-west1-a の nazokake-l4-vm と紐づくディスクを削除中...")
    delete_cmd = f"gcloud compute instances delete nazokake-l4-vm --zone=us-west1-a --project={project_id} --quiet"
    subprocess.run(delete_cmd, shell=True, text=True, capture_output=True)
    print("✅ クリーンアップ完了（無駄なディスク課金をストップしました）。\n")
    
    print("="*60)
    print("🚀 [フェーズ2] L4インスタンス構築の再開 (us-central1-f -> us-east4)")
    print("="*60)
    
    # central1の残りゾーンと、枯渇時のためのeast4（米国東部・同料金帯）フォールバック
    target_zones = ["us-central1-f", "us-east4-a", "us-east4-b", "us-east4-c"]
    success = False
    
    for zone in target_zones:
        print(f"🔍 ゾーン [{zone}] のL4在庫を確認し、構築を試みます...")
        
        create_cmd = (
            "gcloud compute instances create nazokake-l4-vm "
            f"--project={project_id} "
            f"--zone={zone} "
            "--machine-type=g2-standard-4 "
            "--accelerator=type=nvidia-l4,count=1 "
            "--maintenance-policy=TERMINATE "
            "--image-family=common-cu129-ubuntu-2204-nvidia-580 "
            "--image-project=deeplearning-platform-release "
            "--boot-disk-size=150GB "
            "--boot-disk-type=pd-balanced "
            "--metadata=\"install-nvidia-driver=True\""
        )
        
        result = subprocess.run(create_cmd, shell=True, text=True, capture_output=True)
        
        if result.returncode == 0:
            print(f"\n✅ 成功: ゾーン [{zone}] で最強のAI要塞が完成しました！\n{result.stdout}")
            success = True
            break
        else:
            if "ZONE_RESOURCE_POOL_EXHAUSTED" in result.stderr or "unavailable" in result.stderr:
                print(f"⚠️ [{zone}] は現在在庫切れです。次のゾーンへフォールバックします...\n")
                time.sleep(2)
            else:
                print(f"🚨 予期せぬエラーが発生しました ({zone}):\n{result.stderr}")
                sys.exit(1)
                
    if not success:
        print("🚨 [致命的エラー] 候補の全ゾーンでL4の在庫が枯渇しています。時間を置いて再実行してください。")
        sys.exit(1)

if __name__ == "__main__":
    main()
