import subprocess
import sys
import time

def main():
    print("="*60)
    print("🚀 [完全自動探査] G2サポートゾーンを動的取得してL4インスタンスを構築します")
    print("="*60)
    
    project_id_cmd = "gcloud config get-value project"
    project_id = subprocess.run(project_id_cmd, shell=True, text=True, capture_output=True).stdout.strip()
    
    print("🔍 G2インスタンス (L4 GPU) が物理的に配備されている US ゾーンを検索中...")
    # USリージョン（料金が最安クラス）でG2が存在するゾーンだけを抽出
    zone_cmd = 'gcloud compute machine-types list --filter="name=g2-standard-4 AND zone:us-" --format="value(zone)"'
    zone_result = subprocess.run(zone_cmd, shell=True, text=True, capture_output=True)
    
    if zone_result.returncode != 0:
        print(f"🚨 ゾーン情報の取得に失敗しました:\n{zone_result.stderr}")
        sys.exit(1)
        
    valid_zones = [z.strip() for z in zone_result.stdout.split('\n') if z.strip()]
    
    if not valid_zones:
        print("🚨 USリージョン内にG2インスタンスをサポートするゾーンが見つかりません。")
        sys.exit(1)
        
    # 本命の us-central1 を優先的に探索するようソート
    valid_zones.sort(key=lambda x: (0 if 'us-central1' in x else 1, x))
    
    print(f"✅ 物理的に設備が存在する対象ゾーンを {len(valid_zones)} 件特定しました。順番に在庫を探査します...\n")
    
    success = False
    for zone in valid_zones:
        print(f"▶️ ゾーン [{zone}] で構築を試行します...")
        
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
            print(f"\n🎉 成功: ゾーン [{zone}] で最強のAI要塞が完成しました！\n{result.stdout}")
            success = True
            break
        else:
            err_msg = result.stderr
            if "ZONE_RESOURCE_POOL_EXHAUSTED" in err_msg or "unavailable" in err_msg:
                print(f"  ⚠️ [{zone}] は現在在庫切れです。次へ進みます。")
            elif "already exists" in err_msg:
                print(f"  🚨 [{zone}] に既に同名のインスタンスが存在します。")
                sys.exit(1)
            else:
                # 予期せぬエラーの最後の1行だけを表示して次へ進む（止まらない）
                print(f"  🚨 エラー ({zone}): {err_msg.strip().splitlines()[-1]}")
        
        time.sleep(2) # APIのレートリミット（連投制限）回避
        
    if not success:
        print("\n🚨 [致命的エラー] 探索したすべてのUSゾーンでL4の在庫が枯渇しているか、エラーが発生しました。")
        sys.exit(1)

if __name__ == "__main__":
    main()
