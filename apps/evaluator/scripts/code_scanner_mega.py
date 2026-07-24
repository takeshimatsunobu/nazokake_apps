import os
import requests

# ==========================================
# 🗺️ 陣取りゲーム：全区画の設定
# ==========================================
TARGET_ZONES = {
    "第1陣_backend_services": "backend/services",
    "第2陣_backend_api": "backend/api",
    "第3陣_frontend": "frontend"
}

def get_target_files(target_dir):
    """AIがパンクしないよう、解析すべき安全なファイルだけを抽出する"""
    valid_files = []
    if not os.path.exists(target_dir):
        return valid_files
        
    for root, dirs, files in os.walk(target_dir):
        # AIに読ませてはいけないブラックリスト（自動生成フォルダ等）を除外
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('node_modules', '__pycache__', 'build', 'dist', 'out')]
        
        for f in files:
            # 解析対象の拡張子
            if f.endswith(('.py', '.js', '.ts', '.jsx', '.tsx', '.html')) and not f.startswith('__'):
                filepath = os.path.join(root, f)
                # ファイルサイズ制限 (50KB以上はLLMのコンテキスト限界を超えるためスキップ)
                if os.path.getsize(filepath) < 50 * 1024:
                    valid_files.append(filepath)
    return valid_files

def run_mega_scan():
    print("\n================ [ 🚀 究極自動化: 全区画一括メガ・スキャン起動 ] ================")
    url = "http://localhost:11434/api/generate"
    os.makedirs("data", exist_ok=True)
    
    total_files_scanned = 0
    
    for zone_name, directory in TARGET_ZONES.items():
        print(f"\n🚩 【{zone_name}】 のスキャンを開始します (対象: {directory})")
        
        target_files = get_target_files(directory)
        if not target_files:
            print(f"  ⚠️ {directory} に対象ファイルが見つからないためスキップします。")
            continue
            
        # 区画ごとにレポートを分割して生成
        report_path = f"data/code_audit_{zone_name}.md"
        with open(report_path, "w", encoding="utf-8") as report:
            report.write(f"# 📑 ローカルAI自動コード監査レポート ({zone_name})\n\n")
            report.write(f"## 🎯 対象ディレクトリ: {directory}\n\n")
            
            for idx, file_path in enumerate(target_files, 1):
                print(f" 🔍 [{idx}/{len(target_files)}] 解析中: {os.path.basename(file_path)} ...")
                
                with open(file_path, "r", encoding="utf-8") as src_f:
                    code_content = src_f.read()
                
                prompt = f"""
                あなたは凄腕のシニアシステムアーキテクトです。以下のコードを詳細に解析し、どこからも呼び出されていない不要な関数、冗長なエラーハンドリング、または断捨離（削除）すべきデッドコードの候補を特定してください。
                
                【出力フォーマット遵守】
                以下の3つの見出しを含めてマークダウン形式で出力してください。
                ### 1. 判定結果 (安全に削除可能か、維持すべきか)
                ### 2. 削除・修正すべき具体的な理由と根拠
                ### 3. ターミナルまたはVS Code（Continue）での具体的な操作指示
                
                【対象ファイル: {file_path}】
                {code_content}
                """
                
                payload = {
                    "model": "gemma4:e4b",
                    "prompt": prompt,
                    "stream": False
                }
                
                try:
                    # タイムアウトを 600秒 (10分) に設定し、LLMに余裕を持たせる
                    response = requests.post(url, json=payload, timeout=600.0)
                    response.raise_for_status()
                    ai_analysis = response.json().get("response", "解析エラー")
                    
                    report.write(f"## 📄 ファイル: {file_path}\n")
                    report.write(ai_analysis)
                    report.write("\n\n---\n\n")
                    print("      ✅ 完了 (レポート追記済)")
                    total_files_scanned += 1
                except requests.exceptions.Timeout:
                    print("      🚨 【タイムアウト】10分経過しても応答がありません。スキップします。")
                except Exception as e:
                    print(f"      🚨 解析エラー: {e}")
                    
        print(f"🎉 {zone_name} のスキャンが完了！ ({report_path} に保存)")

    print("\n================================================================")
    print(f"🏆 全区画のメガ・スキャンが完了しました！（合計 {total_files_scanned} ファイル解析）")
    print("💡 次のステップ: 生成された各 md ファイルを読みながら、VS Codeの Continue (/clean) で手動断捨離を行います。")

if __name__ == "__main__":
    run_mega_scan()
