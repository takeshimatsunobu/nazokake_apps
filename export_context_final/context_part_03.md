

# ==========================================
# 📄 File: .\scripts\code_scanner.py
# ==========================================
```py
import os
import json
import requests

def scan_codebase(target_dir="backend/services"):
    print(f"\n================ [ コード自動監査スキャン起動 ] ================")
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
                print(f"      ✅ 解析完了。レポートに書き込みました。")
            except Exception as e:
                print(f"      🚨 解析中にエラーが発生しました: {e}")
                
    print(f"\n🎉 全ファイルの監査が完了しました！")
    print(f"📂 レポートが {report_path} に出力されました。ファイルを開いて指示を確認してください。")

if __name__ == "__main__":
    scan_codebase()

```


# ==========================================
# 📄 File: .\scripts\code_scanner_mega.py
# ==========================================
```py
import os
import json
import requests
import time

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
                    print(f"      ✅ 完了 (レポート追記済)")
                    total_files_scanned += 1
                except requests.exceptions.Timeout:
                    print(f"      🚨 【タイムアウト】10分経過しても応答がありません。スキップします。")
                except Exception as e:
                    print(f"      🚨 解析エラー: {e}")
                    
        print(f"🎉 {zone_name} のスキャンが完了！ ({report_path} に保存)")

    print(f"\n================================================================")
    print(f"🏆 全区画のメガ・スキャンが完了しました！（合計 {total_files_scanned} ファイル解析）")
    print("💡 次のステップ: 生成された各 md ファイルを読みながら、VS Codeの Continue (/clean) で手動断捨離を行います。")

if __name__ == "__main__":
    run_mega_scan()

```


# ==========================================
# 📄 File: .\scripts\diagnose_db.py
# ==========================================
```py
import firebase_admin
from firebase_admin import firestore
from collections import Counter
import traceback

def diagnose_database():
    print("\n================ [ ファクト確認: Firestore 全件 構造診断 ] ================")
    try:
        if not firebase_admin._apps:
            firebase_admin.initialize_app()
        db = firestore.client()
        
        print("⏳ データベース全体を高速スキャン中... (数秒〜数十秒お待ちください)")
        
        # 通信量を極限まで減らすため、'status' と 'timestamp' のキーだけをピンポイントで抽出
        docs = db.collection("nazokake_items").select(['status', 'timestamp']).stream()
        
        total_count = 0
        status_counter = Counter()
        missing_timestamp_count = 0
        status_2_missing_ts = 0
        
        for doc in docs:
            total_count += 1
            data = doc.to_dict()
            
            # 1. ステータスの集計
            status = data.get('status', 'MISSING (キーなし)')
            status_counter[str(status)] += 1
            
            # 2. timestamp欠損の集計
            if 'timestamp' not in data:
                missing_timestamp_count += 1
                if status == 2 or status == '2':
                    status_2_missing_ts += 1

        print(f"\n📊 【診断結果】")
        print(f"総ドキュメント数: {total_count} 件")
        
        print("\n📈 ステータス別の内訳:")
        # 件数が多い順に並び替えて表示
        for stat, count in status_counter.most_common():
            print(f"  - status: {stat} -> {count} 件")
            
        print("\n⚠️ 隠れたリスク (サイレント・ドロップの確認):")
        print(f"  - timestampが存在しないデータ総数: {missing_timestamp_count} 件")
        print(f"  - (うち、status: 2 なのに欠損しているため除外されたデータ: {status_2_missing_ts} 件)")
        
        print("\n💡 結論:")
        if status_2_missing_ts > 0:
            print(f"  Firestoreの仕様により、{status_2_missing_ts}件の status:2 データが暗黙的に除外されていました！")
        else:
            print("  暗黙の除外はありません。抽出件数の違いは、単に他のステータスが存在するためです。")

    except Exception as e:
        print(f"🚨 診断中にエラーが発生しました:")
        traceback.print_exc()

if __name__ == "__main__":
    diagnose_database()

```


# ==========================================
# 📄 File: .\scripts\dump_status.py
# ==========================================
```py
import os
from pathlib import Path
from datetime import datetime

def dump_project_status():
    root_dir = Path(os.getcwd())
    print(f"🔍 プロジェクトステータスをスキャン中: {root_dir.name}")
    
    target_exts = {'.py', '.json', '.html', '.js', '.yaml'}
    exclude_dirs = {'.venv', '.venv_ai', '__pycache__', '.git', 'node_modules', '.vscode'}
    
    file_list = []
    for path in root_dir.rglob('*'):
        if path.is_file() and path.suffix in target_exts:
            if not any(part in exclude_dirs for part in path.parts):
                stat = path.stat()
                mod_time = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                file_list.append(f"{path.relative_to(root_dir)} (Last Modified: {mod_time})")
    
    print("\n📁 【主要ファイル構成と最終更新日時】")
    for f in sorted(file_list):
        print(f"  - {f}")
        
    print("\n✅ ダンプ完了。この出力結果をGeminiに共有してください。")

if __name__ == "__main__":
    try:
        dump_project_status()
    except Exception as e:
        print(f"❌ エラー発生（位置特定: dump_project_status）: {e}")

```


# ==========================================
# 📄 File: .\scripts\dynamic_gcp_build.py
# ==========================================
```py
import os
import subprocess
import sys
import time

def main():
    print("="*60)
    print("🚀 [完全自動探査] G2サポートゾーンを動的取得してL4インスタンスを構築します")
    print("="*60)
    
    project_id_cmd = "gcloud config get-value project"
    project_id = subprocess.run(project_id_cmd, shell=True, text=True, capture_output=True).stdout.strip()
    
    print("🔍 G2インスタンス (L4 GPU) が物理的に配備されている US ゾーンを検索中...")
    # USリージョン（料金が最安クラス）でG2が存在するゾーンだけを抽出
    zone_cmd = 'gcloud compute machine-types list --filter="name=g2-standard-4 AND zone:us-" --format="value(zone)"'
    zone_result = subprocess.run(zone_cmd, shell=True, text=True, capture_output=True)
    
    if zone_result.returncode != 0:
        print(f"🚨 ゾーン情報の取得に失敗しました:\n{zone_result.stderr}")
        sys.exit(1)
        
    valid_zones = [z.strip() for z in zone_result.stdout.split('\n') if z.strip()]
    
    if not valid_zones:
        print("🚨 USリージョン内にG2インスタンスをサポートするゾーンが見つかりません。")
        sys.exit(1)
        
    # 本命の us-central1 を優先的に探索するようソート
    valid_zones.sort(key=lambda x: (0 if 'us-central1' in x else 1, x))
    
    print(f"✅ 物理的に設備が存在する対象ゾーンを {len(valid_zones)} 件特定しました。順番に在庫を探査します...\n")
    
    success = False
    for zone in valid_zones:
        print(f"▶️ ゾーン [{zone}] で構築を試行します...")
        
        create_cmd = (
            "gcloud compute instances create nazokake-l4-vm "
            f"--project={project_id} "
            f"--zone={zone} "
            "--machine-type=g2-standard-4 "
            "--accelerator=type=nvidia-l4,count=1 "
            "--maintenance-policy=TERMINATE "
            "--image-family=common-cu129-ubuntu-2204-nvidia-580 "
            "--image-project=deeplearning-platform-release "
            "--boot-disk-size=150GB "
            "--boot-disk-type=pd-balanced "
            "--metadata=\"install-nvidia-driver=True\""
        )
        
        result = subprocess.run(create_cmd, shell=True, text=True, capture_output=True)
        
        if result.returncode == 0:
            print(f"\n🎉 成功: ゾーン [{zone}] で最強のAI要塞が完成しました！\n{result.stdout}")
            success = True
            break
        else:
            err_msg = result.stderr
            if "ZONE_RESOURCE_POOL_EXHAUSTED" in err_msg or "unavailable" in err_msg:
                print(f"  ⚠️ [{zone}] は現在在庫切れです。次へ進みます。")
            elif "already exists" in err_msg:
                print(f"  🚨 [{zone}] に既に同名のインスタンスが存在します。")
                sys.exit(1)
            else:
                # 予期せぬエラーの最後の1行だけを表示して次へ進む（止まらない）
                print(f"  🚨 エラー ({zone}): {err_msg.strip().splitlines()[-1]}")
        
        time.sleep(2) # APIのレートリミット（連投制限）回避
        
    if not success:
        print("\n🚨 [致命的エラー] 探索したすべてのUSゾーンでL4の在庫が枯渇しているか、エラーが発生しました。")
        sys.exit(1)

if __name__ == "__main__":
    main()

```


# ==========================================
# 📄 File: .\scripts\extract_dpo_data.py
# ==========================================
```py
import json
import os
import random
from pathlib import Path
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.base_query import FieldFilter

def extract_dpo_dataset_v6():
    current_dir = Path.cwd()
    key_path = current_dir / "backend" / "serviceAccountKey.json"
    
    if not firebase_admin._apps:
        if key_path.exists():
            cred = credentials.Certificate(str(key_path))
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()
            
    db = firestore.client()
    print("🚀 救出開始！ status:2 のデータから user_evaluations を抽出中...")
    
    # 警告を避けて安全にクエリ
    docs = db.collection("nazokake_items").where(filter=FieldFilter("status", "==", 2)).stream()
    
    good_items = []
    bad_items = []
    
    for doc in docs:
        data = doc.to_dict()
        evals = data.get("user_evaluations", [])
        
        # 評価配列が存在しない、または空の場合はスキップ
        if not evals or not isinstance(evals, list):
            continue
            
        # 配列の中から最新の評価（配列の最後尾）または最大の評価を取得する
        # ここではシンプルに、配列内にある最初の評価スコアを採用する
        score = evals[0].get("user_score", 0)
        
        # 抽出条件
        if score >= 3:
            good_items.append({
                "odai": data.get("A_TITLE", ""),
                "text": data.get("nazokake_text", "")
            })
        elif score <= 2 and score > 0: # 0（未評価）は弾く
            bad_items.append({
                "odai": data.get("A_TITLE", ""),
                "text": data.get("nazokake_text", "")
            })
            
    print(f"📊 Chosen候補 (スコア3以上): {len(good_items)}件")
    print(f"📊 Rejected候補 (スコア1, 2): {len(bad_items)}件")
    
    dpo_dataset = []
    pair_count = min(len(good_items), len(bad_items))
    
    if pair_count > 0:
        random.shuffle(good_items)
        random.shuffle(bad_items)
        for i in range(pair_count):
            dpo_dataset.append({
                "prompt": f"お題「{good_items[i]['odai']}」で、誰もが納得する大衆性を持った秀逸ななぞかけを作成してください。",
                "chosen": good_items[i]['text'],
                "rejected": bad_items[i]['text']
            })
            
    output_dir = current_dir / "data"
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / "dpo_dataset.jsonl"
    
    with open(output_path, "w", encoding="utf-8") as f:
        for item in dpo_dataset:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
            
    print(f"✅ DPO用データ抽出完了: {len(dpo_dataset)}件のペアを {output_path} に保存しました。")

if __name__ == "__main__":
    extract_dpo_dataset_v6()

```


# ==========================================
# 📄 File: .\scripts\extract_firestore_data_all.py
# ==========================================
```py
import os
import json
import traceback
import firebase_admin
from firebase_admin import credentials, firestore

# ==========================================
# 🛡️ 型変換のヘルパー関数 (深い階層まで探索)
# ==========================================
def make_serializable(obj):
    """
    辞書やリストの奥深くまで潜り、Firestore特有の型（Datetime等）を
    JSONで保存できる文字列に変換する。
    """
    if isinstance(obj, dict):
        return {k: make_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [make_serializable(v) for v in obj]
    elif hasattr(obj, 'isoformat'):
        # DatetimeWithNanoseconds などの日付型を文字列にする
        return obj.isoformat()
    # 必要であれば、Firestoreの参照型（DocumentReference）などもここで処理可能
    elif hasattr(obj, 'path'): 
        return obj.path
    else:
        return obj

def extract_all_raw_data():
    print("\n================ [ フェーズ3改: Firestore 全件 深層抽出 ] ================")
    try:
        if not firebase_admin._apps:
            firebase_admin.initialize_app()
        
        db = firestore.client()
        
        print("⏳ Firestoreから 'status: 2' の【全データ】を取得中... (通信に数分かかる場合があります)")
        
        docs = db.collection("nazokake_items").where("status", "==", 2).order_by("timestamp", direction=firestore.Query.DESCENDING).stream()
        
        extracted_data = []
        count = 0
        for doc in docs:
            # 取得したデータを、深い階層まで全て安全な型に変換する
            safe_data = make_serializable(doc.to_dict())
            
            extracted_data.append({
                "id": doc.id,
                "data": safe_data
            })
            
            count += 1
            if count % 1000 == 0:
                print(f"  ... {count}件 取得完了")
        
        if not extracted_data:
            print("⚠️ 警告: 対象データが見つかりませんでした。")
            return

        os.makedirs("data", exist_ok=True)
        output_file = "data/raw_firestore_dump_all.json"
        
        print("💾 データをローカルファイルに保存しています...")
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(extracted_data, f, ensure_ascii=False, indent=2)
            
        print(f"✅ 抽出完了！ 合計 {len(extracted_data)}件のデータを {output_file} に保存しました。")

    except Exception as e:
        print(f"🚨 データ抽出中に致命的エラーが発生しました:")
        traceback.print_exc()

if __name__ == "__main__":
    extract_all_raw_data()

```


# ==========================================
# 📄 File: .\scripts\extract_sft_data.py
# ==========================================
```py
import json
import os
from google.cloud import firestore

db = firestore.Client()

def extract_sft_data():
    print("🧠 [Phase 2] AI育成(SFT)用データの抽出を開始します...")
    
    # 評価完了(status=2)のデータを取得
    docs = db.collection("nazokake_items").where("status", "==", 2).stream()
    
    sft_data = []
    for doc in docs:
        data = doc.to_dict()
        odai = data.get("A_TITLE", "")
        nazo = data.get("nazokake_text", "")
        
        # お題とテキストが両方存在する場合のみ抽出
        if odai and nazo:
            sft_data.append({
                "messages": [
                    {"role": "user", "content": f"お題「{odai}」でなぞかけを作ってください。"},
                    {"role": "model", "content": nazo}
                ]
            })
            
    # dataフォルダが無ければ作成
    os.makedirs("data", exist_ok=True)
    
    # JSONL形式（1行1JSON）で書き出し
    output_path = "data/sft_dataset.jsonl"
    with open(output_path, "w", encoding="utf-8") as f:
        for item in sft_data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
            
    print(f"✅ 抽出完了！ 合計 {len(sft_data)} 件の学習用データを '{output_path}' に生成しました。")

if __name__ == "__main__":
    extract_sft_data()

```


# ==========================================
# 📄 File: .\scripts\gather_evidence.py
# ==========================================
```py
import os
import json
import urllib.request
import time

def gather_evidence():
    print("\n================ [ ファクト収集: デプロイ・パイプラインの真相究明 ] ================")

    # --------------------------------------------------
    # 証拠2: デプロイ先ディレクトリの真実 (firebase.json)
    # --------------------------------------------------
    print("\n🔍 [証拠2] firebase.json の公開ディレクトリ設定:")
    public_dir = None
    if os.path.exists("firebase.json"):
        try:
            with open("firebase.json", "r", encoding="utf-8") as f:
                fb_data = json.load(f)
                public_dir = fb_data.get("hosting", {}).get("public")
                if public_dir:
                    print(f"  👉 Firebaseが本番に上げているフォルダ: 【 {public_dir} 】")
                else:
                    print("  👉 publicディレクトリの指定が見つかりません。")
        except Exception as e:
            print(f"  🚨 読み込みエラー: {e}")
    else:
        print("  ⚠️ firebase.json が見つかりません。")

    # --------------------------------------------------
    # 証拠3: ビルド工程の真実 (package.json)
    # --------------------------------------------------
    print("\n🔍 [証拠3] package.json のビルド工程 (npm run build):")
    if os.path.exists("package.json"):
        try:
            with open("package.json", "r", encoding="utf-8") as f:
                pkg_data = json.load(f)
                build_script = pkg_data.get("scripts", {}).get("build")
                if build_script:
                    print(f"  👉 ビルドコマンドが存在します: 【 {build_script} 】")
                    print("     (※デプロイ前に npm run build を実行する必要があるプロジェクトです)")
                else:
                    print("  👉 ビルドコマンドは未設定です (ビルド不要の可能性大)。")
        except Exception as e:
            print(f"  🚨 読み込みエラー: {e}")
    else:
        print("  👉 package.json が見つかりません。(ビルド不要の純粋なHTML/JS構成と推測されます)")

    # --------------------------------------------------
    # 証拠1: 本番サーバー(URL)に上がっているコードの実態
    # --------------------------------------------------
    print("\n🔍 [証拠1] 本番サーバー上のコード実態:")
    print("  ... Googleのサーバー(nazokakeapp-137e5.web.app)に直接アクセスして中身を確認中...")
    
    # URLにランダムな数字(タイムスタンプ)をつけて、CDNのキャッシュを強制的に突破する
    url = f"https://nazokakeapp-137e5.web.app/app_final.js?v={int(time.time())}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as response:
            live_code = response.read().decode('utf-8')
            
            if "total_score" in live_code:
                print("  👉 判定: 新しいコード (total_score) が【本番に届いています】！")
                print("     💡 結論: デプロイは成功しています。Takeshiさんのブラウザのキャッシュが強すぎることが唯一の原因です。")
            elif "s_total" in live_code:
                print("  👉 判定: 本番のコードは古いまま (s_total のみ) です。")
                if public_dir and public_dir != "frontend":
                    print(f"     💡 結論: 私たちが修正した 'frontend' フォルダと、Firebaseがアップロードした '{public_dir}' フォルダがズレている「デプロイ空振り」が原因です。")
                else:
                    print("     💡 結論: 修正パッチがうまく当たっていないか、ビルド漏れが原因です。")
            else:
                print("  👉 判定: どちらの変数名も見つかりませんでした。別のファイルで処理されている可能性があります。")
    except urllib.error.URLError as e:
        print(f"  🚨 本番URLからの取得に失敗しました (404 Not Found等の場合、ファイル名やパスが違う可能性があります): {e}")
    except Exception as e:
         print(f"  🚨 本番URLからの取得中に予期せぬエラーが発生しました: {e}")

    print("\n=========================================================================")

if __name__ == "__main__":
    gather_evidence()

```


# ==========================================
# 📄 File: .\scripts\inject_backend_url.py
# ==========================================
```py
import subprocess
import re
from pathlib import Path

PROJECT_ID = "nazokakeapp-137e5"
SERVICE_NAME = "nazokake-backend"

print(f"🔍 [Phase 1] Cloud Run（{SERVICE_NAME}）の本番URLを自動探査中...")
try:
    # gcloudコマンドでCloud RunのURLを直接取得
    res = subprocess.run(
        ["gcloud", "run", "services", "list", "--project", PROJECT_ID, "--filter", f"metadata.name={SERVICE_NAME}", "--format", "value(status.url)"],
        capture_output=True, text=True, check=True
    )
    backend_url = res.stdout.strip()
    
    if not backend_url:
        print(f"⚠️ Cloud Run上に '{SERVICE_NAME}' が見つかりません。")
        print("💡 バックエンドがまだデプロイされていないか、プロジェクトIDが異なる可能性があります。")
    else:
        print(f"✅ バックエンドURLを確保: {backend_url}")
        
        js_path = Path("frontend/app_final.js")
        if js_path.exists():
            text = js_path.read_text(encoding="utf-8")
            # 前回のバッチで入れた仮置きURLを、取得した本番URLに書き換え
            text = re.sub(r'const CLOUD_RUN_URL = "[^"]+";', f'const CLOUD_RUN_URL = "{backend_url}";', text)
            js_path.write_text(text, encoding="utf-8")
            print("✅ app_final.js に本番バックエンドURLの注入が完了しました！")
            
        print("\n🚀 [Phase 2] Firebase Hostingへの本番デプロイ準備が完了しました！")
        print("   ターミナルで以下のコマンドを実行し、フロントエンドを世界に公開してください:")
        print("   firebase deploy --only hosting")

except Exception as e:
    print(f"🚨 エラー発生: gcloudコマンドが実行できないか、GCPの認証が切れています。\n詳細: {e}")

```


# ==========================================
# 📄 File: .\scripts\inject_firestore_batch.py
# ==========================================
```py
import json
import os
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import traceback

def restore_types(data):
    """文字列になっている日付データを、Firestoreが愛する本物の時刻型に蘇生させる"""
    for key in ["timestamp", "evaluated_at", "created_at"]:
        if key in data and isinstance(data[key], str):
            try:
                # ISO 8601文字列をPythonのdatetimeオブジェクトに変換
                ts_str = data[key].replace("Z", "+00:00")
                data[key] = datetime.fromisoformat(ts_str)
            except Exception:
                pass
    return data

def inject_to_firestore():
    print("\n================ [ 最終フェーズ: 本番Firestore 高速一括注入 (Batched Writes) ] ================")
    
    if not firebase_admin._apps:
        firebase_admin.initialize_app()
    db = firestore.client()

    clean_file_path = "data/clean_prod_dump_9500.jsonl"
    if not os.path.exists(clean_file_path):
        print(f"🚨 エラー: クリーンデータ ({clean_file_path}) が見つかりません。")
        return

    print("⏳ ローカルのクリーンデータを読み込んでいます...")
    cleaned_items = []
    with open(clean_file_path, "r", encoding="utf-8") as f:
        for line in f:
            cleaned_items.append(json.loads(line.strip()))

    total_items = len(cleaned_items)
    print(f"📊 注入準備完了: {total_items}件のデータを本番に反映します。")
    print("🚀 Google Cloudへ高速一括送信を開始します (数十秒〜数分かかります)...")

    # Firestoreは最大500件ずつしか一括処理できないため、チャンク（塊）に分ける
    CHUNK_SIZE = 400
    success_count = 0

    for i in range(0, total_items, CHUNK_SIZE):
        chunk = cleaned_items[i:i + CHUNK_SIZE]
        batch = db.batch()
        
        for item in chunk:
            doc_id = item["id"]
            data = restore_types(item["data"])
            
            # ドキュメントの参照を取得し、バッチに「更新(merge=True)」の指示を追加
            doc_ref = db.collection("nazokake_items").document(doc_id)
            batch.set(doc_ref, data, merge=True)
            
        try:
            # チャンクをまとめて送信（コミット）
            batch.commit()
            success_count += len(chunk)
            print(f"  ... {success_count}/{total_items} 件 反映完了")
        except Exception as e:
            print(f"  🚨 バッチ送信エラー (チャンク {i}〜): {e}")

    print(f"\n🎉 注入ミッション・コンプリート！")
    print(f"🏆 合計 {success_count}件 のピカピカのデータが、本番データベースに完全上書きされました。")

if __name__ == "__main__":
    try:
        inject_to_firestore()
    except Exception as e:
        print(f"🚨 致命的なエラー: {e}")
        traceback.print_exc()

```


# ==========================================
# 📄 File: .\scripts\llm_deadcode_reviewer.py
# ==========================================
```py
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

```


# ==========================================
# 📄 File: .\scripts\local_gemma_api.py
# ==========================================
```py
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

```


# ==========================================
# 📄 File: .\scripts\publish_jobs.py
# ==========================================
```py
from google.cloud.firestore_v1.base_query import FieldFilter
import concurrent.futures
import json
import logging
from google.cloud import firestore
from google.cloud import pubsub_v1

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# プロジェクトIDとトピック名（実行環境に合わせて調整してください）
PROJECT_ID = "nazokakeapp-137e5" 
TOPIC_ID = "nazokake-eval-topic"

def publish_jobs():
    """Firestoreの未処理データを抽出し、Pub/Subへ一括Publishする"""
    db = firestore.Client()
    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(PROJECT_ID, TOPIC_ID)

    logger.info("Firestoreから未処理(status=0)のドキュメントを検索します...")
    
    # メモリ枯渇を防ぐため stream() を使用してカーソルベースで取得
    docs = db.collection("nazokake_items").where(filter=FieldFilter("status", "==", 0)).stream()

    publish_count = 0
    futures = []

    for doc in docs:
        payload = {"document_id": doc.id}
        data_bytes = json.dumps(payload).encode("utf-8")

        # Pub/Subへ非同期でPublish
        future = publisher.publish(topic_path, data=data_bytes)
        futures.append(future)
        publish_count += 1

        if publish_count % 1000 == 0:
            logger.info(f"{publish_count}件のメッセージをPublishしました...")

    # すべての非同期Publishがネットワーク送信を完了するまで待機
    if futures:
        concurrent.futures.wait(futures) 
           
    logger.info(f"✅ 合計 {publish_count} 件のジョブをPub/Subへキューイングしました。")

if __name__ == "__main__":
    publish_jobs()
```


# ==========================================
# 📄 File: .\scripts\rescue_zombies_safe.py
# ==========================================
```py
import sys
import asyncio
from pathlib import Path
import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

sys.path.append(str(Path.cwd() / "backend"))
from services.ai_service import evaluate_and_update_task

async def process_zombies():
    load_dotenv()
    key_path = Path.cwd() / "backend" / "serviceAccountKey.json"
    if not firebase_admin._apps:
        if key_path.exists():
            cred = credentials.Certificate(str(key_path))
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()
            
    db = firestore.client()
    
    print("🔍 データベースからデータを一括でメモリに読み込みます（タイムアウト対策）...")
    
    # 同期I/Oブロッキングを防ぐため to_thread で実行
    all_docs = await asyncio.to_thread(lambda: list(db.collection("nazokake_items").stream()))
    
    zombies = []
    for doc in all_docs:
        data = doc.to_dict()
        status = data.get("status", 0)
        eval_status = data.get("eval_status", "")
        
        # 完了(2, "completed") または エラー(-1, "error") 以外の「鑑定中」を抽出
        if status not in [2, "completed", -1, "error"] and eval_status not in ["completed", "error"]:
            zombies.append((doc.id, data.get("A_TITLE", "不明"), data.get("nazokake_text", "")))
    
    if not zombies:
        print("\n✨ 素晴らしい！『鑑定中』で止まっているゾンビデータは1件もありませんでした。")
        return

    print(f"\n🧟 {len(zombies)}件のゾンビデータを発見。順次救出を開始します...")
    
    count = 0
    for doc_id, title, text in zombies:
        print(f"\n🚀 AI評価エンジン起動: お題「{title}」")
        try:
            # Phase 1 で非同期化(async def)された関数を正しく await する
            await evaluate_and_update_task(db, doc_id, title, text)
            count += 1
            print(f"✅ 「{title}」の評価・保存処理が完了しました！")
        except Exception as e:
            print(f"🚨 救出失敗 「{title}」: {e}")

    print(f"\n🎉 計 {count} 件のゾンビデータの評価・救出が完了しました！")

def rescue_zombies_safe():
    asyncio.run(process_zombies())

if __name__ == "__main__":
    rescue_zombies_safe()

```


# ==========================================
# 📄 File: .\scripts\run_local_eval.py
# ==========================================
```py
import os
import sys
from pathlib import Path
import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

# backendフォルダ内のモジュールを読み込めるようにパスを追加
sys.path.append(str(Path.cwd() / "backend"))
from services.ai_service import evaluate_and_update_task

def run_local_evaluation():
    load_dotenv() # 環境変数（APIキー等）の読み込み
    
    key_path = Path.cwd() / "backend" / "serviceAccountKey.json"
    
    # 🚨 修正ポイント: 以前成功した「安全な認証フォールバック」を追加
    if not firebase_admin._apps:
        if key_path.exists():
            cred = credentials.Certificate(str(key_path))
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()
            
    db = firestore.client()
    
    print("🔍 未評価 (status: 0) の注入作品を捜索中...")
    try:
        docs = db.collection("nazokake_items").where("author", "==", "Takeshi_Gemini_Brainstorm").stream()
        
        found = False
        for doc in docs:
            data = doc.to_dict()
            if data.get("status") != 0:
                continue
                
            found = True
            doc_id = doc.id
            title = data.get("A_TITLE", "不明")
            text = data.get("nazokake_text", "")
            
            print(f"\n🚀 お題: {title} の評価エンジンをローカルで直接起動します！")
            
            # 魔法のAI関数を直接呼び出し
            evaluate_and_update_task(db, doc_id, title, text)
            print(f"✅ {title} の評価・保存が完了しました！")

        if not found:
            print("⚠️ 未評価のデータは見つかりませんでした。")
            
    except Exception as e:
        print(f"🚨 エラー発生: {e}")

if __name__ == "__main__":
    run_local_evaluation()

```


# ==========================================
# 📄 File: .\scripts\scan_streamlit.py
# ==========================================
```py
from pathlib import Path

print("🤖 プロジェクト内のStreamlitファイルをスキャンしています...")
st_files = []
for p in Path('.').rglob('*.py'):
    # 環境依存フォルダやゴミ箱は厳格に除外
    if any(x in p.parts for x in ['.venv', '.venv_ai', 'node_modules', '_archive_trash']):
        continue
    try:
        content = p.read_text(encoding='utf-8')
        if 'import streamlit' in content:
            st_files.append(p)
    except:
        pass

if not st_files:
    print("\n⚠️ StreamlitのPythonファイルが見つかりません。完全にゼロから『新規作成』するフェーズです。")
else:
    for f in st_files:
        print(f"\n{'='*50}\n📄 発見: {f}\n{'='*50}")
        # 先頭30行（インポートや初期化ロジック）を抽出
        lines = f.read_text(encoding='utf-8').split('\n')[:30]
        print('\n'.join(lines))

```


# ==========================================
# 📄 File: .\scripts\seed_rag_data.py
# ==========================================
```py
import time
from pathlib import Path
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from sentence_transformers import SentenceTransformer

def seed_rag_database_glucose_v2():
    current_dir = Path.cwd()
    key_path = current_dir / "backend" / "serviceAccountKey.json"
    
    if not firebase_admin._apps:
        if key_path.exists():
            cred = credentials.Certificate(str(key_path))
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()
            
    db = firestore.client()
    
    print("🚀 国産AIの最新版（GLuCoSE v2）をロード中...")
    
    # 💡 修正1: 精度が向上した「v2」モデルに変更
    # 💡 修正2: カスタムトークナイザーの実行を明示的に許可する trust_remote_code=True を追加
    model = SentenceTransformer('pkshatech/GLuCoSE-base-ja-v2', trust_remote_code=True)

    print("🔍 Firestoreから全データ（status: 2）を取得中...")
    docs = db.collection("nazokake_items").where(filter=FieldFilter("status", "==", 2)).stream()

    items_to_insert = []
    for doc in docs:
        data = doc.to_dict()
        odai = data.get("A_TITLE")
        nazokake = data.get("nazokake_text")
        
        if odai and nazokake:
            items_to_insert.append({
                "id": doc.id,
                "odai": odai,
                "nazokake": nazokake
            })

    total_count = len(items_to_insert)
    print(f"✅ 合計 {total_count} 件のデータを取得しました。")
    
    if total_count == 0:
        print("🚨 データが見つかりませんでした。")
        return

    odai_list = [item["odai"] for item in items_to_insert]

    print(f"🧠 {total_count}件のお題をベクトル化中... (PCのパワーを使います。数分お待ちください)")
    embeddings = model.encode(odai_list, show_progress_bar=True)
    
    print("\n✅ 解析完了。Firestoreへの一括保存を開始します...")
    collection_ref = db.collection("nazokake_rag_knowledge")
    
    batch = db.batch()
    batch_count = 0
    total_inserted = 0

    for i, item in enumerate(items_to_insert):
        embedding_list = embeddings[i].tolist()
        
        try:
            doc_ref = collection_ref.document(item["id"])
            batch.set(doc_ref, {
                "odai": item["odai"],
                "nazokake": item["nazokake"],
                "embedding": embedding_list
            })
            
            batch_count += 1
            total_inserted += 1
            
            if batch_count >= 400:
                batch.commit()
                print(f"  ... {total_inserted} / {total_count} 件登録完了")
                batch = db.batch()
                batch_count = 0
                
        except Exception as e:
             print(f"⚠️ 保存エラー (お題: {item['odai']}): {e}")

    if batch_count > 0:
        batch.commit()
        print(f"  ... {total_inserted} / {total_count} 件登録完了")

    print(f"🎉 完璧です！全 {total_inserted} 件の国産AIベースRAGデータベース構築が完了しました！")

if __name__ == "__main__":
    seed_rag_database_glucose_v2()

```


# ==========================================
# 📄 File: .\scripts\setup_gcp_l4_instance.py
# ==========================================
```py
import os
import subprocess
import sys
import time

def main():
    print("="*60)
    print("🚀 GCP L4インスタンス構築を開始します (在庫自動探査モード)")
    print("="*60)
    
    project_id_cmd = "gcloud config get-value project"
    project_id_result = subprocess.run(project_id_cmd, shell=True, text=True, capture_output=True)
    project_id = project_id_result.stdout.strip()
    
    if not project_id or "none" in project_id.lower():
        print("🚨 GCPプロジェクトが設定されていません。'gcloud auth login' を実行し、プロジェクトをセットしてください。")
        sys.exit(1)
    
    print(f"対象プロジェクト: {project_id}\n")
    
    target_zones = ["us-central1-a", "us-central1-b", "us-central1-c", "us-central1-f"]
    
    success = False
    
    for zone in target_zones:
        print(f"🔍 ゾーン [{zone}] のL4在庫を確認し、構築を試みます...")
        
        create_cmd = (
            "gcloud compute instances create nazokake-l4-vm "
            f"--project={project_id} "
            f"--zone={zone} "
            "--machine-type=g2-standard-4 "
            "--accelerator=type=nvidia-l4,count=1 "
            "--maintenance-policy=TERMINATE "
            "--image-family=common-cu129-ubuntu-2204-nvidia-580 "
            "--image-project=deeplearning-platform-release "
            "--boot-disk-size=150GB "
            "--boot-disk-type=pd-balanced "
            "--metadata=\"install-nvidia-driver=True\""
        )
        
        result = subprocess.run(create_cmd, shell=True, text=True, capture_output=True)
        
        if result.returncode == 0:
            print(f"\n✅ 成功: ゾーン [{zone}] でインスタンスの確保と起動要求が完了しました！")
            
            # 修正: アーキテクチャの限界を引き出す llama-server の最適化コマンドを明示
            print("\n" + "="*60)
            print("🔥 【GPU極限スループット化コマンド】 🔥")
            print("SSH接続後、以下のオプションを付与して llama-server を起動してください。")
            print("L4 GPU (24GB) の全層オフロードとバッチサイズ最適化により生成速度が劇的に向上します：")
            print("\n  ./llama-server -m <あなたのGemmaモデルパス.gguf> \\")
            print("    --port 8080 --host 0.0.0.0 \\")
            print("    -ngl 99 -c 2048 -b 512 -ub 512 --flash-attn")
            print("="*60 + "\n")
            
            success = True
            break
        else:
            if "ZONE_RESOURCE_POOL_EXHAUSTED" in result.stderr or "unavailable" in result.stderr:
                print(f"⚠️ [{zone}] は現在在庫切れです。次のゾーンへフォールバックします...\n")
                time.sleep(2) 
            else:
                print(f"🚨 予期せぬエラーが発生しました ({zone}):\n{result.stderr}")
                sys.exit(1)
                
    if not success:
        print("🚨 [致命的エラー] 指定したすべてのゾーンでL4 GPUの在庫が枯渇しています。")
        print("数時間後に再度実行するか、別のリージョン（us-east4等）へ変更する必要があります。")
        sys.exit(1)

if __name__ == "__main__":
    main()

```


# ==========================================
# 📄 File: .\scripts\start_vertex_tuning.py
# ==========================================
```py
import time
from google.cloud import storage
import vertexai
from vertexai.tuning import sft

# --- 設定 ---
PROJECT_ID = "nazokakeapp-137e5"
REGION = "asia-northeast1"  # チューニングが未対応の場合は us-central1 等に変更が必要になる可能性があります
BUCKET_NAME = f"nazokake-training-data-{PROJECT_ID}"
LOCAL_FILE = "data/sft_dataset.jsonl"
GCS_FILE_PATH = f"gs://{BUCKET_NAME}/sft_dataset.jsonl"

BASE_MODEL = "gemini-3.1-flash" 

def start_tuning():
    print(f"🧠 Vertex AI ファインチューニングジョブの起動中... (ベース: {BASE_MODEL})")
    
    try:
        # Vertex AIの初期化
        vertexai.init(project=PROJECT_ID, location=REGION)
        
        # SFTジョブの作成と送信 (正しいモジュールを使用)
        sft_tuning_job = sft.train(
            source_model=BASE_MODEL,
            train_dataset=GCS_FILE_PATH,
            epochs=3,
            learning_rate_multiplier=1.0,
        )
        
        print("\n🎉 ジョブの送信に成功しました！")
        print(f"   ジョブ情報: {sft_tuning_job}")
        print("   Google Cloud Consoleの [Vertex AI] > [モデルレジストリ] または [チューニング] から進捗を確認できます。")
        
    except Exception as e:
        print(f"\n🚨 ジョブの送信中にGCP側からエラーが返されました:\n{e}")
        print("\n※考えられる原因: 指定したベースモデル（プレビュー版）またはリージョン（東京）が、SFTに未対応である可能性があります。")

if __name__ == "__main__":
    # バケットへのアップロードは先ほど成功しているためスキップし、ジョブ起動のみ行います
    start_tuning()

```


# ==========================================
# 📄 File: .\scripts\test_inference.py
# ==========================================
```py
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

```


# ==========================================
# 📄 File: .\scripts\train_local_gemma.py
# ==========================================
```py
import torch
import torch._inductor.config  # 念のための安全装置
from unsloth import FastLanguageModel
from trl import SFTTrainer
from transformers import TrainingArguments
from datasets import load_dataset

# 設定
max_seq_length = 2048
dtype = None
load_in_4bit = True

# 👑 Gemma 4 E4B (Tier 1 ローカルモデル)
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name = "unsloth/gemma-4-e4b-it-bnb-4bit",
    max_seq_length = max_seq_length,
    dtype = dtype,
    load_in_4bit = load_in_4bit,
)

# LoRA設定
model = FastLanguageModel.get_peft_model(
    model,
    r = 16,
    target_modules = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj",],
    lora_alpha = 16,
    lora_dropout = 0,
    bias = "none",
    use_gradient_checkpointing = "unsloth",
)

# データの読み込み
dataset = load_dataset("json", data_files="data/sft_dataset_formatted.jsonl", split="train")

# 学習の実行
trainer = SFTTrainer(
    model = model,
    tokenizer = tokenizer,
    train_dataset = dataset,
    dataset_text_field = "text",
    max_seq_length = max_seq_length,
    args = TrainingArguments(
        per_device_train_batch_size = 2,
        gradient_accumulation_steps = 4,
        warmup_steps = 5,
        max_steps = 60,
        learning_rate = 2e-4,
        fp16 = not torch.cuda.is_bf16_supported(),
        bf16 = torch.cuda.is_bf16_supported(),
        logging_steps = 1,
        output_dir = "outputs",
    ),
)
trainer.train()

# 保存
model.save_pretrained("gemma4_e4b_nazokake_model")
tokenizer.save_pretrained("gemma4_e4b_nazokake_model")
print("🎉 なぞかけ専用 Gemma 4 E4B が誕生しました！")

```


# ==========================================
# 📄 File: .\scripts\wake_up_vm.py
# ==========================================
```py
import subprocess
import sys
import time

def run_cmd(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)

def main():
    print("="*60)
    print("☀️ GCP要塞を確実に叩き起こす（IP自動追従版）")
    print("="*60)
    
    # プロジェクトIDとゾーンの取得
    proj = run_cmd("gcloud config get-value project").stdout.strip()
    zone = run_cmd('gcloud compute instances list --filter="name=nazokake-l4-vm" --format="value(zone)"').stdout.strip()

    if not zone:
        print("🚨 VMが見つかりません。GCPコンソールを確認してください。")
        sys.exit(1)

    print(f"📍 要塞を発見 (Zone: {zone})。起動コマンドを送信します...")
    run_cmd(f"gcloud compute instances start nazokake-l4-vm --zone={zone} --project={proj} --quiet")

    print("⏳ OSとSSHサーバーの完全起動を待機中 (30秒)...")
    for i in range(30, 0, -5):
        print(f"   ... 残り {i} 秒")
        time.sleep(5)

    print("🔄 変更された外部IPアドレスを検知し、VS Codeの接続設定 (~/.ssh/config) を更新します...")
    res = run_cmd(f"gcloud compute config-ssh --project={proj} --quiet")
    if res.returncode != 0:
        print(f"🚨 SSH設定の更新に失敗しました:\n{res.stderr}")
        sys.exit(1)
        
    print("✅ 設定更新完了！")

    target_host = f"nazokake-l4-vm.{zone}.{proj}"
    print(f"\n🚪 新しいVS Codeウィンドウで要塞への扉を開きます: {target_host}")
    subprocess.run(f"code --remote ssh-remote+{target_host}", shell=True)

if __name__ == "__main__":
    main()

```


# ==========================================
# 📄 File: .\service_frontend\admin_app.py
# ==========================================
```py
import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.base_query import FieldFilter
import pandas as pd
import os

# ==========================================
# 🛡️ 1. セキュリティゲート（防弾パスワードロック）
# ==========================================
st.set_page_config(page_title="謎掛け学術振興会 統合コックピット", layout="wide", page_icon="🎛️")

ADMIN_PASS = os.environ.get("ADMIN_PASS", "dojoyaburi2026")
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.markdown("<h2 style='text-align: center; color: #4A593D;'>🎛️ 謎掛け学術振興会 統合コックピット</h2>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center;'>管理者権限の認証が必要です。</p>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        pwd = st.text_input("アクセスコード", type="password")
        if st.button("システム起動", use_container_width=True):
            if pwd == ADMIN_PASS:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("認証に失敗しました。アクセスは記録されます。")
    st.stop()

# ==========================================
# 🔌 2. Firebase バックエンド接続
# ==========================================
if not firebase_admin._apps:
    firebase_admin.initialize_app()
db = firestore.client()

st.title("🎛️ 統合コックピット (Admin Console)")
st.markdown("SPA（表玄関）から収集されたデータの監視、強化学習の確定、AIのチューニングを行います。")

# ==========================================
# 🗂️ 3. コア機能ナビゲーション
# ==========================================
tab_patrol, tab_rlhf, tab_tune = st.tabs([
    "🚨 荒らし監視・パトロール", 
    "👑 RLHF ゴールデンデータ確定", 
    "⚙️ AIエンジン チューンナップ"
])

# ------------------------------------------
# 機能A: 荒らし監視・パトロール
# ------------------------------------------
with tab_patrol:
    st.subheader("🚨 ユーザー評価パトロール")
    st.write("SPAから投稿された直近のユーザー評価（スコア）を監視し、不正な評価を除外します。")
    
    if st.button("🔄 最新の評価ログを取得"):
        st.session_state.patrol_data_loaded = True
        
    try:
        docs = db.collection('nazokake_items').order_by('timestamp', direction=firestore.Query.DESCENDING).limit(100).stream()
        patrol_items = []
        for doc in docs:
            data = doc.to_dict()
            evals = data.get('user_evaluations', [])
            if evals:
                patrol_items.append({
                    "無効化対象": False, # 👈 これがチェックボックスになります
                    "ID": doc.id,
                    "お題": data.get("A_TITLE", ""),
                    "なぞかけ本文": data.get("nazokake_text", ""),
                    "評価数": len(evals),
                    "直近のユーザー評価": evals[-1].get("user_score", "N/A"), # 👈 名前を直感的に変更
                    "AIスコア": data.get("s_total", "N/A")
                })
                
        if patrol_items:
            import pandas as pd
            df = pd.DataFrame(patrol_items)
            
            # 💡 st.data_editor を使ってチェックボックス付きのインタラクティブな表を描画
            edited_df = st.data_editor(
                df,
                use_container_width=True,
                hide_index=True,
                disabled=["ID", "お題", "なぞかけ本文", "評価数", "直近のユーザー評価", "AIスコア"] # チェックボックス以外は編集不可にする
            )
            
            st.markdown("#### 🗑️ 異常データの無効化")
            if st.button("⚠️ チェックしたデータを一括無効化する"):
                # チェックが入っている行だけを抽出して一括処理
                to_delete = edited_df[edited_df["無効化対象"] == True]
                if not to_delete.empty:
                    for _, row in to_delete.iterrows():
                        db.collection('nazokake_items').document(row["ID"]).update({"status": -1})
                    st.success(f"✅ {len(to_delete)} 件のデータを無効化しました！もう一度「🔄 最新の評価ログを取得」を押して更新してください。")
                else:
                    st.warning("無効化するデータにチェックを入れてください。")
        else:
            st.info("現在、監視対象となる新しいユーザー評価はありません。")
    except Exception as e:
        st.error(f"データ取得エラー: {e}")

# ------------------------------------------
# 機能B: RLHF ゴールデンデータ確定 (クラウドソーシング承認)
# ------------------------------------------
with tab_rlhf:
    st.subheader("👑 コミュニティ主導 RLHF 承認コンソール")
    st.write("一般ユーザーが評価・添削したデータを名匠が最終検品し、純度100%の『ゴールデンデータ（Status: 2）』へ昇格させます。")

    if st.button("🔄 最新の検品待ちデータを取得"):
        st.session_state.rlhf_loaded = True

    try:
        # 🛡️ 100件の地平線バグ防止策：ステータスが0（未確定）か1（AI評価済）のものを全域からスキャン
        from google.cloud.firestore_v1.base_query import FieldFilter
        docs = db.collection('nazokake_items').where(filter=FieldFilter('status', 'in', [0, 1])).stream()
        target_item = None
        
        for doc in docs:
            data = doc.to_dict()
            evals = data.get('user_evaluations', [])
            
            # 💡 ユーザーの評価（または添削）が1つ以上あるものを発見した瞬間にループを抜ける
            if len(evals) > 0:
                target_item = data
                target_item['id'] = doc.id
                break
                
        if target_item:
            odai = target_item.get('A_TITLE', '不明')
            original_text = target_item.get('nazokake_text', 'テキストなし')
            evals = target_item.get('user_evaluations', [])
            
            # ユーザー評価の集計
            valid_scores = [e.get('user_score') for e in evals if e.get('user_score') is not None]
            avg_score = sum(valid_scores) / len(valid_scores) if valid_scores else 3.0
            user_corrections = [e.get('correction') for e in evals if e.get('correction') and e.get('correction').strip()]
            
            # プレースホルダー（ユーザーの添削があればそれを、なければオリジナルをセット）
            best_correction = user_corrections[-1] if user_corrections else original_text

            st.markdown("### 🔍 審査対象")
            st.info(f"**【お題】** {odai}")
            st.info(f"**【オリジナルAI作品】**
{original_text}")
            
            st.markdown("### 📊 コミュニティの反応")
            col_score, col_corr = st.columns([1, 2])
            with col_score:
                st.metric("ユーザー評価平均", f"{avg_score:.1f} 点", f"投票数: {len(evals)}")
            with col_corr:
                if user_corrections:
                    st.write("**ユーザーからの添削提案:**")
                    for i, corr in enumerate(user_corrections):
                        st.markdown(f"> {corr}")
                else:
                    st.write("※ 添削提案はありません。スコアのみの投票です。")

            st.markdown("---")
            st.markdown("### 👨‍🏫 名匠の最終承認")
            with st.form(key=f"form_rlhf_curation"):
                final_text = st.text_area("📝 最終ゴールデンテキスト (ユーザー提案をそのまま採用、または修正してください)", value=best_correction, height=100)
                admin_score = st.slider("⚖️ 最終人間評価 (1-5) ※AIの学習用指標になります", 1, 5, int(round(avg_score)))
                
                col_btn1, col_btn2 = st.columns(2)
                with col_btn1:
                    if st.form_submit_button("👑 ゴールデンデータとして確定 (Status: 2)", use_container_width=True):
                        db.collection('nazokake_items').document(target_item['id']).update({
                            "nazokake_text": final_text,
                            "status": 2,
                            "admin_score": admin_score,
                            "is_golden": True
                        })
                        st.success("✅ 承認しました！AIの教科書（フロントエンド新着）へ登録されました。")
                        st.rerun()
                with col_btn2:
                    if st.form_submit_button("🗑️ 基準未達で棄却 (Status: -1)", use_container_width=True):
                        db.collection('nazokake_items').document(target_item['id']).update({
                            "status": -1
                        })
                        st.warning("⚠️ 棄却しました。このデータは無効化されます。")
                        st.rerun()
        else:
            st.success("🎉 現在、コミュニティからの検品待ちデータはありません！ユーザーの参加を待ちましょう。")
            
    except Exception as e:
        st.error(f"データ取得エラー: {e}")

# ------------------------------------------
# 機能C: AIエンジン チューンナップ
# ------------------------------------------
with tab_tune:
    st.subheader("⚙️ バックエンドAI チューニング")
    st.write("Cloud Run (Dual AI Core) が使用するプロンプトやパラメーターを動的に変更します。")
    
    # Firestoreのシステム設定コレクションを読み込む
    config_ref = db.collection('system_config').document('ai_settings')
    config_doc = config_ref.get()
    
    current_temp = 0.7
    current_prompt = "あなたはなぞかけの名匠です。"
    
    if config_doc.exists:
        data = config_doc.to_dict()
        current_temp = data.get("temperature", 0.7)
        current_prompt = data.get("system_prompt", current_prompt)
        
    with st.form("tuning_form"):
        new_temp = st.slider("Temperature (温度: 創造性のブレ幅)", 0.0, 1.0, float(current_temp), 0.1)
        new_prompt = st.text_area("System Prompt (AIへの絶対指示)", value=current_prompt, height=150)
        
        if st.form_submit_button("🚀 バックエンド設定を即時反映"):
            config_ref.set({
                "temperature": new_temp,
                "system_prompt": new_prompt,
                "updated_at": firestore.SERVER_TIMESTAMP
            }, merge=True)
            st.success("AIのパラメーターを更新しました。次回のSPAからの生成・鑑定リクエストから適用されます。")

```
