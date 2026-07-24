import os
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel

def unwrap_clippable_linear(module):
    """PEFT互換性パッチ（内部レイヤーの抽出手術）"""
    for name, child in module.named_children():
        if child.__class__.__name__ == "Gemma4ClippableLinear":
            setattr(module, name, child.linear)
        else:
            unwrap_clippable_linear(child)

def main():
    print("🚀 チャットテンプレートを適用したローカル推論テストを開始します...")
    
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    LORA_PATH = os.path.join(BASE_DIR, "models", "nazokake_model")
    BASE_MODEL = "unsloth/gemma-4-E4B-it"

    if not os.path.exists(LORA_PATH):
        print(f"🚨 エラー: LoRAモデルが見つかりません。パスを確認してください: {LORA_PATH}")
        return

    print("🧠 トークナイザー（辞書）をロードしています...")
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, use_fast=False)

    print("⚙️ ベースモデルをGPUに強制収容してロードしています...")
    base_model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        device_map="cuda",
        torch_dtype=torch.float16,
    )

    print("🔧 PEFT互換性パッチを適用しています...")
    unwrap_clippable_linear(base_model)

    print("⚡ 鍛え上げたLoRAアダプタ（なぞかけの脳波）を結合しています...")
    model = PeftModel.from_pretrained(base_model, LORA_PATH)

    theme = "人工知能"
    
    # 💡 修正ポイント: AIが「指示」だと認識できる公式の会話フォーマットを作成
    messages = [
        {"role": "user", "content": f"お題「{theme}」で、面白いなぞかけを作ってください。"}
    ]
    # トークナイザーを使って、Gemma専用の特殊な包装紙で包む
    prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    
    print(f"\n🎤 お題: {theme}")
    print("🤖 AIが考えています...\n")
    print("-" * 50)

    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=200,
            temperature=0.7,
            top_p=0.9,
            repetition_penalty=1.1,
        )

    generated_text = tokenizer.decode(outputs[0][inputs['input_ids'].shape[1]:], skip_special_tokens=True)
    
    print(generated_text.strip())
    print("-" * 50)
    print("\n🎉 フルパワー推論テストが完璧に完了しました！")

if __name__ == "__main__":
    main()
