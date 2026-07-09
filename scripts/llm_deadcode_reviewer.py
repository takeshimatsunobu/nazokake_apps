import os
import urllib.request
import json
import sys

OLLAMA_GENERATE_URL = "http://localhost:11434/api/generate"
OLLAMA_TAGS_URL = "http://localhost:11434/api/tags"
OUTPUT_PS1 = r"_ai_context\execute_cleanup.ps1"

def get_ollama_model():
    """利用可能なモデル（Gemma等）を動的取得"""
    try:
        req = urllib.request.Request(OLLAMA_TAGS_URL)
        with urllib.request.urlopen(req, timeout=3.0) as res:
            data = json.loads(res.read().decode("utf-8"))
            models = [m["name"] for m in data.get("models", [])]
            gemma = next((m for m in models if "gemma" in m.lower()), None)
            return gemma or (models[0] if models else None)
    except Exception:
        return None

def analyze_with_llm(model, filepath, snippet):
    """LLMにコードを読ませて判定"""
    prompt = f"""あなたはシニアPythonアーキテクトです。
以下のファイルはプロジェクト内に存在するスクリプトです。

ファイルパス: {filepath}
コードの先頭部分:
{snippet}

このコードが「一時的な使い捨てスクリプトや過去のテストの残骸（archive）」であるか、あるいは「本番環境で必要なコアファイルや起動スクリプト（keep）」であるかを判定してください。
以下のJSONフォーマットのみで回答してください。挨拶は不要です。
{{"action": "archive", "reason": "アーカイブすべき理由、または残すべき理由"}}
※使い捨てと判断した場合は "archive"、本番コードの場合は "keep" にしてください。"""

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1}
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(OLLAMA_GENERATE_URL, data=data, headers={"Content-Type": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=120) as res:
            result = json.loads(res.read().decode("utf-8"))
            return json.loads(result.get("response", "{}"))
    except Exception as e:
        return {"action": "error", "reason": str(e)}

def main():
    model = get_ollama_model()
    if not model:
        print("❌ [Fail-Fast] OllamaのAPIに接続できません。Ollamaが起動しているか確認してください。")
        sys.exit(1)

    print(f"🤖 モデル '{model}' で仕分けを開始します...")
    
    # 探索対象: ルート直下 と scriptsフォルダ 内の .py ファイル
    target_files = []
    
    # ルート直下
    for f in os.listdir("."):
        if os.path.isfile(f) and f.endswith(".py"):
            target_files.append(f)
            
    # scripts直下
    if os.path.exists("scripts"):
        for f in os.listdir("scripts"):
            if os.path.isfile(os.path.join("scripts", f)) and f.endswith(".py"):
                target_files.append(os.path.join("scripts", f))

    ps1_commands = [
        "# 自動生成された退避用スクリプト",
        "Write-Host '🧹 ゴミ箱(_archive_scripts)への移動を開始します...' -ForegroundColor Cyan"
    ]

    for filepath in target_files:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                snippet = "".join(f.readlines()[:50])
        except Exception:
            continue
            
        print(f"👀 審査中: {filepath} ...", end=" ", flush=True)
        result = analyze_with_llm(model, filepath, snippet)
        
        action = result.get("action")
        reason = result.get("reason", "")
        
        if action == "archive":
            print(f"🗑️ [Archive] 理由: {reason}")
            # 安全のため移動先フォルダが存在しない場合に備えたパス指定
            ps1_commands.append(f"Move-Item -Path '{filepath}' -Destination '_archive_scripts' -Force -ErrorAction SilentlyContinue")
            ps1_commands.append(f"Write-Host '  Moved: {filepath}'")
        elif action == "keep":
            print(f"🛡️ [Keep] 理由: {reason}")
        else:
            print(f"⚠️ [Error/Skip] {reason}")

    # ps1ファイルへ書き出し
    with open(OUTPUT_PS1, "w", encoding="utf-8") as f:
        f.write("\n".join(ps1_commands) + "\nWrite-Host '✅ 退避完了！' -ForegroundColor Green\n")
        
    print(f"\n🎉 審査完了！ 退避コマンドを {OUTPUT_PS1} に生成しました。")

if __name__ == "__main__":
    main()
