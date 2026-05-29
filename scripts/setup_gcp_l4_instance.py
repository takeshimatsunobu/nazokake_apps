import os
import subprocess
import sys
import time

def main():
    print("="*60)
    print("🚀 GCP L4インスタンス構築を開始します (在庫自動探査モード)")
    print("="*60)
    
    # プロジェクトIDの確認
    project_id_cmd = "gcloud config get-value project"
    project_id_result = subprocess.run(project_id_cmd, shell=True, text=True, capture_output=True)
    project_id = project_id_result.stdout.strip()
    
    if not project_id or "none" in project_id.lower():
        print("🚨 GCPプロジェクトが設定されていません。'gcloud auth login' を実行し、プロジェクトをセットしてください。")
        sys.exit(1)
    
    print(f"対象プロジェクト: {project_id}\n")
    
    # L4 GPUが提供されている us-central1 のゾーンリスト
    target_zones = ["us-central1-a", "us-central1-b", "us-central1-c", "us-central1-f"]
    
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
            print(f"\n✅ 成功: ゾーン [{zone}] でインスタンスの確保と起動要求が完了しました！\n{result.stdout}")
            success = True
            break
        else:
            if "ZONE_RESOURCE_POOL_EXHAUSTED" in result.stderr or "unavailable" in result.stderr:
                print(f"⚠️ [{zone}] は現在在庫切れです。次のゾーンへフォールバックします...\n")
                time.sleep(2)  # APIレートリミット回避のための短い待機
            else:
                print(f"🚨 予期せぬエラーが発生しました ({zone}):\n{result.stderr}")
                sys.exit(1)
                
    if not success:
        print("🚨 [致命的エラー] 指定したすべてのゾーンでL4 GPUの在庫が枯渇しています。")
        print("数時間後に再度実行するか、別のリージョン（us-east4等）へ変更する必要があります。")
        sys.exit(1)

if __name__ == "__main__":
    main()
