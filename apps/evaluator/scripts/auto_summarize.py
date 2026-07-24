import os
import urllib.request
import json
import sys

OLLAMA_URL = "http://localhost:11434/api/generate"
SUMMARY_FILE = "architecture_summary.md"

def get_ollama_model():
    """Ollama APIから利用可能なモデル（Gemma等）を自動探索する"""
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=3.0) as res:
            data = json.loads(res.read().decode("utf-8"))
            models = [m["name"] for m in data.get("models", [])]
            gemma = next((m for m in models if "gemma" in m.lower()), None)
            return gemma or (models[0] if models else None)
    except Exception:
        return None

def main():
    print("🤖 ローカルLLM(Ollama)のAPIを探査しています...")
    model = get_ollama_model()
    
    if not model:
        print("❌ [Fail-Fast] OllamaのAPI(localhost:11434)に接続できませんでした。")
        print("💡 Ollamaアプリが起動しているか確認してください。")
        sys.exit(1)

    print(f"✅ モデル '{model}' を発見しました。プロジェクトの解析を開始します...")

    # 解析対象の拡張子と、無視するディレクトリ（ノイズ排除）
    target_exts = {".py", ".dart"}
    exclude_dirs = {".venv", ".venv_ai", ".venv_stable", "node_modules", ".git", "__pycache__", "build", "android", "ios", "web", "macos", "windows", "linux"}
    
    structure = []
    code_snippets = []
    
    for root, dirs, files in os.walk("."):
        dirs[:] = [d for d in dirs if d not in exclude_dirs]
        rel_dir = os.path.relpath(root, ".")
        if rel_dir != ".":
            structure.append(f"📁 {rel_dir}")
        for file in files:
            ext = os.path.splitext(file)[1]
            if ext in target_exts:
                filepath = os.path.join(root, file)
                structure.append(f"  📄 {file}")
                
                # トークン溢れを防ぐため各ファイルの先頭50行を抽出
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        lines = f.readlines()[:50]
                        code_snippets.append(f"\n--- {filepath} ---\n" + "".join(lines))
                except Exception:
                    pass

    prompt = f"""あなたは優秀なシニアアーキテクトです。
以下の「プロジェクトのフォルダ構成」と「各ファイルの内容」を解析し、アーキテクチャの要約を作成してください。

【出力フォーマット】
以下のマークダウン形式のみを出力してください。挨拶や余計な解説は不要です。

## 1. 全体構造と主要な機能 (Screens/UI & Backend)
（各フォルダの役割と、主要な機能の概要を箇条書きでまとめる）

## 2. 状態管理とデータフロー (State Management)
（データがどこから入力され、どのファイルを通って、どのように処理・保存されるか。APIの流れや状態遷移をまとめる）

---
【フォルダ構成】
{chr(10).join(structure)}

【主要コード（先頭部分）】
{"".join(code_snippets)}
"""

    print("⏳ Ollamaにプロンプトを送信し、推論を実行中です...（数分かかる場合があります。コーヒーブレイクを推奨します☕）")

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(OLLAMA_URL, data=data, headers={"Content-Type": "application/json"})

    try:
        # LLM推論の待機（最大10分）
        with urllib.request.urlopen(req, timeout=600) as res:
            result = json.loads(res.read().decode("utf-8"))
            generated_text = result.get("response", "").strip()
    except Exception as e:
        print(f"❌ LLMの生成中に通信エラーが発生しました: {e}")
        sys.exit(1)

    print(f"✅ 推論完了！ {SUMMARY_FILE} に自動追記します...")
    
    # ファイルの末尾に追記
    with open(SUMMARY_FILE, "a", encoding="utf-8") as f:
        f.write("\n\n" + generated_text + "\n")

    print("🎉 [Success] 全自動要約＆追記が完了しました！")

if __name__ == "__main__":
    main()
