import json
import subprocess
import sys

def main():
    print("="*60)
    print("🔍 [事実確認] タイムアウト後のインスタンス状態（シュレディンガーのVM）を診断します")
    print("="*60)
    
    # 既存のVMが存在するかをJSON形式で取得
    cmd = 'gcloud compute instances list --filter="name=nazokake-l4-vm" --format="json"'
    result = subprocess.run(cmd, shell=True, text=True, capture_output=True)
    
    if result.returncode != 0:
        print(f"🚨 gcloudコマンドの実行に失敗しました [ERROR_LOC_GCLOUD_01]:\n{result.stderr}")
        sys.exit(1)
        
    try:
        instances = json.loads(result.stdout)
        
        if not instances:
            print("✅ 診断結果: インスタンスは全く作成されていません（クリーンな状態です）。")
            print("👉 結論: 課金リスクなし。次のゾーン（us-central1-f 等）から安全に構築を再開できます。")
        else:
            for inst in instances:
                name = inst.get("name")
                zone = inst.get("zone", "").split('/')[-1]
                status = inst.get("status")
                
                print(f"⚠️ 診断結果: インスタンスが既に存在しています！")
                print(f"  - 名前: {name}")
                print(f"  - 存在ゾーン: {zone}")
                print(f"  - 現在のステータス: {status}")
                
                if status == "RUNNING" or status == "PROVISIONING":
                    print("\n👉 結論: タイムアウト裏で構築は成功していました！このままこのVMを使用します。")
                else:
                    print("\n👉 結論: 中途半端な状態です。一度削除（クリーンアップ）が必要です。")
                    
    except json.JSONDecodeError as e:
        print(f"🚨 JSONパースエラー（予期せぬAPIレスポンス）[ERROR_LOC_JSON_01]: {e}")
        print(f"生の出力:\n{result.stdout}")

    print("\n📝 [ストップ] この出力結果をすべてコピーし、Geminiにそのままダンプ（共有）してください。")

if __name__ == "__main__":
    main()
