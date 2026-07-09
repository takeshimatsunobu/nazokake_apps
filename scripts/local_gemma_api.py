import os
import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel

app = FastAPI(title="Local Gemma Nazokake API")

# グローバル変数
model = None
tokenizer = None

class NazokakeRequest(BaseModel):
    theme: str
    prompt_template: str = "" # クラウド側から強力なプロンプトを受け取るための枠

def unwrap_clippable_linear(module):
    """PEFT互換性パッチ"""
    for name, child in module.named_children():
        if child.__class__.__name__ == "Gemma4ClippableLinear":
            setattr(module, name, child.linear)
        else:
            unwrap_clippable_linear(child)

@app.on_event("startup")
def load_model():
    global model, tokenizer
    print("🚀 [起動中] モデルをVRAMにロードしています。少々お待ちください...")
    
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    LORA_PATH = os.path.join(BASE_DIR, "models", "nazokake_model")
    BASE_MODEL = "unsloth/gemma-4-E4B-it"

    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, use_fast=False)
    base_model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL, device_map="cuda", torch_dtype=torch.float16
    )
    unwrap_clippable_linear(base_model)
    model = PeftModel.from_pretrained(base_model, LORA_PATH)
    
    print("✅ [完了] モデルのロード成功！APIリクエストの受付を開始します。 (Port: 8000)")

@app.post("/generate")
def generate_nazokake(req: NazokakeRequest):
    global model, tokenizer
    if model is None:
        raise HTTPException(status_code=503, detail="モデルがまだロードされていません")

    print(f"📩 注文が入りました！ お題: {req.theme}")
    
    # クラウド側からプロンプトの型が送られてこなかった場合のデフォルト
    if not req.prompt_template:
        req.prompt_template = f"お題「{req.theme}」で、面白いなぞかけを作ってください。"

    messages = [{"role": "user", "content": req.prompt_template}]
    prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    
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
    print(f"📤 生成完了: {generated_text.strip()}")
    
    return {"result": generated_text.strip()}

if __name__ == "__main__":
    # ポート8000番でサーバーを起動
    uvicorn.run(app, host="0.0.0.0", port=8000)
