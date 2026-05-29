import os
import requests
import glob

# 取得した最強モデルをセット
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "gemma4:e4b" 

# バックエンドのPythonファイルを全探索
TARGET_FILES = glob.glob("backend/**/*.py", recursive=True)

SYSTEM_PROMPT = """
あなたは超一流のPythonエンジニアです。
入力されたコードから「使われていないテストコード」や「冗長な処理」を削除し、本番環境向けに最適化してください。
【絶対のルール】
・リファクタリング後の完全なコードだけを出力すること。
・バッククォート(`python)などのMarkdown装飾、挨拶、解説は一切禁止。純粋なテキストのみを返すこと。
"""

def clean_code_with_gemma(file_path):
    print(f"🚀 処理中: {file_path}")
    
    with open(file_path, "r", encoding="utf-8") as f:
        original_code = f.read()

    payload = {
        "model": MODEL_NAME,
        "system": SYSTEM_PROMPT,
        "prompt": original_code,
        "stream": False,
        "options": {
            "temperature": 0.1
        }
    }

    try:
        response = requests.post(OLLAMA_URL, json=payload)
        response.raise_for_status()
        cleaned_code = response.json().get("response", "").strip()
        
        # Markdownのゴミを削ぎ落とす
        if cleaned_code.startswith("`python"):
            cleaned_code = cleaned_code[9:-3].strip()
        elif cleaned_code.startswith("`"):
            cleaned_code = cleaned_code[3:-3].strip()
            
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(cleaned_code)
            
        print(f"✅ 完了: {file_path} を上書きしました。")
        
    except Exception as e:
        print(f"❌ エラー ({file_path}): {e}")

if __name__ == "__main__":
    print("================ [ 🧹 メガ・リファクター起動 (gemma4:e4b) ] ================")
    for file in TARGET_FILES:
        clean_code_with_gemma(file)
    print("================ [ 🎉 全ファイルの処理が完了 ] ================")
