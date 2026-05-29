import subprocess
import sys

def main():
    print("="*50)
    print("🔍 [事実確認] GCPに現在存在するDeep Learningイメージを直接検索します...")
    print("="*50)
    
    # gcloudコマンドでイメージファミリーのリストを取得
    cmd = 'gcloud compute images list --project=deeplearning-platform-release --format="value(family)"'
    result = subprocess.run(cmd, shell=True, text=True, capture_output=True)
    
    if result.returncode != 0:
        print(f"🚨 取得エラー:\n{result.stderr}")
        sys.exit(1)

    # 重複を排除してソート
    families = sorted(list(set(result.stdout.splitlines())))
    
    # Ubuntuかつ、CUDA(cu11またはcu12)が含まれるものをフィルタリング
    # Pytorch等があらかじめ入っているとVRAMを圧迫する可能性があるため、common系を優先したい
    target_families = [f for f in families if "ubuntu" in f and ("cu11" in f or "cu12" in f)]

    print("\n✅ 現在利用可能な Ubuntu + CUDA 搭載イメージ一覧:")
    if not target_families:
        print("  ⚠️ 該当するイメージが見つかりませんでした。")
    else:
        for f in target_families:
            # common系を強調表示
            if "common" in f:
                print(f"  ⭐ {f}")
            else:
                print(f"  - {f}")
    
    print("\n📝 [ストップ] この出力結果をすべてコピーし、Geminiにそのままダンプ（共有）してください。")

if __name__ == "__main__":
    main()
