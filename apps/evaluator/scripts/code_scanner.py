import os
import requests

def scan_codebase(target_dir="backend/services"):
    print("\n================ [ コード自動監査スキャン起動 ] ================")
    print(f"🎯 対象ディレクトリ: {target_dir}")
    
    url = "http://localhost:11434/api/generate"
    report_path = "data/code_audit_report.md"
    os.makedirs("data", exist_ok=True)
    
    # 対象フォルダ内の .py ファイルを取得
    try:
        files = [f for f in os.listdir(target_dir) if f.endswith('.py') and f != '__init__.py']
    except FileNotFoundError:
        print(f"🚨 エラー: {target_dir} ディレクトリが見つかりません。")
        return
        
    with open(report_path, "w", encoding="utf-8") as report:
        report.write("# 📑 ローカルAI自動コード監査レポート\n\n")
        report.write("## 📝 概要\n本レポートはローカルLLM (Gemma 4) によって自動生成されたコード断捨離の指示書です。\n\n")
        
        for idx, filename in enumerate(files, 1):
            file_path = os.path.join(target_dir, filename)
            print(f" 🔍 [{idx}/{len(files)}] ファイル解析中: {filename} ...")
            
            with open(file_path, "r", encoding="utf-8") as src_f:
                code_content = src_f.read()
            
            prompt = f"""
            あなたは凄腕のシニアシステムアーキテクトです。以下のPythonコードを詳細に解析し、どこからも呼び出されていない不要な関数、冗長なエラーハンドリング、または断捨離（削除）すべきデッドコードの候補を特定してください。
            
            【出力フォーマット遵守】
            必ず以下の3つの見出しを含めてマークダウン形式で出力してください。
            ### 1. 判定結果 (安全に削除可能か、維持すべきか)
            ### 2. 削除・修正すべき具体的な理由と根拠
            ### 3. ターミナルまたはVS Code（Continue）での具体的な操作指示
            
            【対象ファイル: {filename}】
            {code_content}
            """
            
            payload = {
                "model": "gemma4:e4b",
                "prompt": prompt,
                "stream": False
            }
            
            try:
                response = requests.post(url, json=payload, timeout=60.0)
                response.raise_for_status()
                ai_analysis = response.json().get("response", "解析エラー")
                
                report.write(f"## 📄 ファイル: {file_path}\n")
                report.write(ai_analysis)
                report.write("\n\n---\n\n")
                print("      ✅ 解析完了。レポートに書き込みました。")
            except Exception as e:
                print(f"      🚨 解析中にエラーが発生しました: {e}")
                
    print("\n🎉 全ファイルの監査が完了しました！")
    print(f"📂 レポートが {report_path} に出力されました。ファイルを開いて指示を確認してください。")

if __name__ == "__main__":
    scan_codebase()
