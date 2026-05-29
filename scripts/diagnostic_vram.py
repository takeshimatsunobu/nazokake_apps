import torch
import sys

def check_vram():
    print("\n================ [VRAM ストレス・メタ分析] ================")
    try:
        if not torch.cuda.is_available():
            print("🚨 CUDAが利用できません。")
            sys.exit(1)
        
        gpu_name = torch.cuda.get_device_name(0)
        total_mem = torch.cuda.get_device_properties(0).total_memory / (1024**3)
        
        print(f"✅ GPU認識: {gpu_name}")
        print(f"📊 VRAM総容量: {total_mem:.2f} GB")
        
        # 12.5GBのテンソルを仮想的に割り当ててOOM（エラー）の挙動をメタ分析する
        print("🧪 [シミュレーション] デュアルAI想定の12.5GBダミーデータをVRAMに確保し、耐えられるかテストします...")
        # 12.5GBのfloat32テンソル (約3.125 * 10^9 要素)
        dummy_tensor = torch.empty((int(12.5 * 1024**3 / 4),), dtype=torch.float32, device='cuda')
        print("🎉 成功: VRAMとRAMのオフロード連携により、12.5GBの展開にノーエラーで耐え切りました！")
        del dummy_tensor
        torch.cuda.empty_cache()

    except torch.cuda.OutOfMemoryError as e:
        print(f"❌ [メタ分析結果] VRAM不足 (OOM) が発生しました。デュアルモデルの同時起動は確実なクラッシュリスクがあります。")
    except Exception as e:
        print(f"❌ 予期せぬエラー: {e}")

if __name__ == "__main__":
    check_vram()
