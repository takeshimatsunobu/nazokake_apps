📦 PROJECT TREE (Cleaned)
========================================

├── Dockerfile
├── PROJECT_CORE.md
├── _ai_context
│   ├── execute_cleanup.ps1
│   ├── execute_llm_cleanup.ps1
│   ├── source_code_part_1.txt
│   ├── source_code_part_2.txt
│   ├── source_code_part_3.txt
│   ├── source_code_part_4.txt
│   ├── source_code_part_5.txt
│   ├── source_code_part_6.txt
│   ├── source_code_part_7.txt
│   ├── source_code_part_8.txt
│   └── vulture_report.txt
├── app.py
├── asset_dump.txt
├── backend
│   ├── api
│   │   ├── __init__.py
│   │   ├── endpoints.py
│   │   └── evaluate.py
│   ├── core
│   │   ├── __init__.py
│   │   ├── config.py
│   │   └── prompt_config.json
│   ├── gemini_api.py
│   ├── main.py
│   ├── requirements.txt
│   └── services
│       ├── __init__.py
│       └── ai_service.py
├── export_clean_context.py
├── export_project.py
├── firebase.json
├── firestore.indexes.json
├── firestore.rules
├── firestore_db.py
├── frontend
│   ├── Procfile
│   ├── README.md
│   ├── admin
│   │   ├── admin.js
│   │   └── index.html
│   ├── analysis_options.yaml
│   ├── api_key.txt
│   ├── assets
│   │   └── icon
│   │       └── app_icon.png
│   ├── export_code.ps1
│   ├── firebase.json
│   ├── hard_reset.py
│   ├── nazokake_app.iml
│   ├── patch_appcheck.py
│   ├── patch_errors.py
│   ├── patch_index_html.py
│   ├── patch_rollback.py
│   ├── patch_tabs_and_format.py
│   ├── patch_ui_overwrite.py
│   ├── prompt_for_gemma.txt
│   ├── public
│   │   ├── app.js
│   │   └── index.html
│   ├── requirements.txt
│   └── test
├── hunter_gcp_instance.ps1
├── nazokakeapp-137e5
│   ├── 404.html
│   └── index.html
├── odai.txt
├── requirements.txt
├── scan_regions.ps1
├── scripts
│   ├── assess_baseline.py
│   ├── audit_batch.py
│   ├── audit_training_data.py
│   ├── auto_summarize.py
│   ├── bust_cache.py
│   ├── check_latest_status.py
│   ├── code_scanner.py
│   ├── code_scanner_mega.py
│   ├── diagnose_db.py
│   ├── dump_status.py
│   ├── dynamic_gcp_build.py
│   ├── extract_dpo_data.py
│   ├── extract_firestore_data_all.py
│   ├── extract_sft_data.py
│   ├── gather_evidence.py
│   ├── inject_backend_url.py
│   ├── inject_firestore_batch.py
│   ├── llm_deadcode_reviewer.py
│   ├── local_gemma_api.py
│   ├── publish_jobs.py
│   ├── rescue_zombies_safe.py
│   ├── run_local_eval.py
│   ├── scan_streamlit.py
│   ├── seed_rag_data.py
│   ├── setup_gcp_l4_instance.py
│   ├── start_fortress.ps1
│   ├── start_vertex_tuning.py
│   ├── test_inference.py
│   ├── train_local_gemma.py
│   └── wake_up_vm.py
├── seed_rag_database.py
├── serviceAccountKey.json
├── service_frontend
│   └── admin_app.py
├── skills-lock.json
├── unsloth_compiled_cache
│   └── moe_utils.py
└── utils
    ├── find_assets.py
    ├── find_assets_to_file.py
    └── llm_router.py


# ==========================================
# 📄 File: .\app.py
# ==========================================
```py
import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.base_query import FieldFilter
import json
import re
import pandas as pd
import plotly.express as px
import os
from utils.llm_router import DualAIRouter

# 🛡️ セキュリティゲート（パスワードロック）
ADMIN_PASS = os.environ.get("ADMIN_PASS", "dojoyaburi2026")
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.markdown("<h2 style='text-align: center; color: #4A593D;'>🌸 名匠鑑定室 ログイン</h2>", unsafe_allow_html=True)
    pwd = st.text_input("合言葉を入力してください", type="password")
    if st.button("入室"):
        if pwd == ADMIN_PASS:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("合言葉が違います。")
    st.stop()

# Firebase初期化
if not firebase_admin._apps:
    firebase_admin.initialize_app()
db = firestore.client()

st.set_page_config(page_title="なぞかけ道場プロジェクト", layout="wide", page_icon="🌸")
router = DualAIRouter()

# 🌸 白ベース（和紙×抹茶×桜）テーマCSS
st.markdown("""
<style>
    .stApp { background-color: #FAFAFA; color: #333333; font-family: 'Noto Serif JP', serif; }
    h1, h2, h3 { color: #4A593D; border-bottom: 2px solid #E892A3; padding-bottom: 10px; }
    .stTextInput>div>div>input, .stTextArea>div>div>textarea { background-color: #FFFFFF; color: #333333; border: 1px solid #8A9A5B; }
    .stButton>button { background-color: #4A593D; color: #FFFFFF; font-weight: bold; border: none; border-radius: 8px; transition: all 0.3s ease; }
    .stButton>button:hover { background-color: #E892A3; color: #FFFFFF; }
    .report-box { background-color: #FFFFFF; border-left: 6px solid #4A593D; padding: 20px; border-radius: 8px; margin-top: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }
    .context-box { background-color: #FFF0F5; padding: 15px; border-radius: 8px; margin-top: 10px; color: #555555; font-size: 0.9em; }
    .rlhf-box { background-color: #f8f9fa; border: 2px dashed #8A9A5B; padding: 20px; border-radius: 8px; }
</style>
""", unsafe_allow_html=True)

st.title("🌸 なぞかけ道場 (Dual AI Core)")

# 復旧したナビゲーション
tabs = ["💡 AI生成", "✍️ 自作鑑定", "🌱 評価して育てる", "👑 殿堂入り"]
selected_tab = st.sidebar.radio("ナビゲーション", tabs)

if selected_tab == "💡 AI生成":
    st.subheader("Tier 1 (Gemini 3.5 Flash) による高速なぞかけ創出")
    topic = st.text_input("お題を入力", "お茶")
    
    if st.button("✨ なぞかけを生成する"):
        system_prompt = "あなたは伝説的ななぞかけの名匠です。なぞかけの極意は、「そのこころ」に【同音異義語】を使って、お題と無関係なものを鮮やかに結びつけることです。大衆性を持った秀逸ななぞかけを1つ作成してください。解説は不要です。"
        user_prompt = f"お題「{topic}」で、面白いなぞかけを作成してください。\nフォーマット:\n〇〇とかけて、\n××ととく。\nそのこころは、\n□□でしょう。"
        
        with st.spinner("名匠が思考中..."):
            result = router.generate_chat(system_prompt, user_prompt, tier=1, max_tokens=150)
            if result["error"]:
                st.error(f"エラー: {result['error']}")
            else:
                ai_text = result['text']
                st.markdown(f"<div class='report-box'><h3>🍵 生成結果</h3><p style='font-size: 1.5em; font-weight: bold;'>{ai_text}</p></div>", unsafe_allow_html=True)
                try:
                    db.collection('nazokake_items').document().set({
                        "A_TITLE": topic,
                        "nazokake_text": ai_text,
                        "generator": "gemini-3.5-flash",
                        "created_at": firestore.SERVER_TIMESTAMP,
                        "status": 0
                    })
                    st.toast("✅ クラウドデータとして保存しました！")
                except Exception as e:
                    st.error(f"⚠️ 保存エラー: {e}")

elif selected_tab == "✍️ 自作鑑定":
    st.subheader("【極】 マルチエージェント11軸精密鑑定")
    col1, col2 = st.columns(2)
    with col1:
        odai = st.text_input("お題 (A)", "サウナ")
        kake = st.text_input("〇〇とかけて (A')", "整う")
    with col2:
        toku = st.text_input("××ととく (B)", "時計")
        kokoro = st.text_input("そのこころは (C)", "どちらも針（張り）が気になります")
        
    if st.button("⚖️ 鑑定の儀を開始する"):
        nazokake_text = f"「{odai}」とかけて、「{kake}」ととく。そのこころは、「{kokoro}」。"
        
        with st.spinner("🔍 辞書エージェントが日本の文化背景・隠れた文脈を解析中..."):
            ctx_result = router.generate_chat("あなたは文化背景抽出エージェントです。事実と文脈だけを簡潔に出力してください。", f"お題「{odai}」、掛け「{kake}」、解き「{toku}」、こころ「{kokoro}」の文化的背景を解説してください。", tier=1)
            if ctx_result["error"]: st.stop()
            context_text = ctx_result["text"]

        with st.spinner("⚖️ 最高峰のAI審査員が採点中..."):
            judge_sys = """あなたは「最高峰の審査員（AI落語家）」です。以下の11の評価軸（0.0〜1.0）でスコアリングし、JSONフォーマットのみで出力してください。
{"scores": {"意外性": 0.0, "納得感": 0.0, "技巧性": 0.0, "ユーモア": 0.0, "情景喚起": 0.0, "リズム": 0.0, "独自性": 0.0, "大衆性": 0.0, "文化的深み": 0.0, "言葉の美しさ": 0.0, "総合評価": 0.0}, "comment": "講評"}"""
            judge_user = f"【なぞかけ】\n{nazokake_text}\n\n【文化背景】\n{context_text}"
            judge_result = router.generate_chat(judge_sys, judge_user, tier=2, max_tokens=500, temperature=0.2)
            
            if not judge_result["error"]:
                try:
                    match = re.search(r'\{.*\}', judge_result["text"], re.DOTALL)
                    eval_data = json.loads(match.group(0)) if match else {}
                    scores = eval_data.get("scores", {})
                    comment = eval_data.get("comment", "")
                    
                    df = pd.DataFrame(dict(r=list(scores.values()), theta=list(scores.keys())))
                    fig = px.line_polar(df, r='r', theta='theta', line_close=True, range_r=[0, 1.0])
                    fig.update_traces(fill='toself', line_color='#4A593D', fillcolor='rgba(232, 146, 163, 0.4)')
                    fig.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font_color='#333333')
                    
                    col_chart, col_comment = st.columns([1, 1])
                    with col_chart: st.plotly_chart(fig, use_container_width=True)
                    with col_comment:
                        st.markdown(f"<div class='report-box'><h3>🍵 審査員（AI落語家）より</h3><p>{comment}</p></div>", unsafe_allow_html=True)
                        st.markdown(f"<div class='context-box'><strong>【抽出された文化背景】</strong><br>{context_text}</div>", unsafe_allow_html=True)
                except Exception: st.error("JSONパース失敗")

elif selected_tab == "🌱 評価して育てる":
    st.subheader("RLHFアノテーション・データフィードバック")
    st.markdown("AIが生成した未評価のなぞかけを名匠（あなた）が採点・添削し、未来の学習データを作成します。")
    
    if 'current_eval_item' not in st.session_state:
        st.session_state.current_eval_item = None

    def fetch_next_item():
        try:
            # 本番DBから未評価（status:0）を取得する元の仕様
            docs = db.collection('nazokake_items').where(filter=FieldFilter('status', '==', 0)).limit(1).stream()
            for doc in docs:
                item = doc.to_dict()
                item['id'] = doc.id
                return item
            return None
        except Exception as e:
            st.error(f"🚨 データ取得エラー: {e}")
            return None

    if not st.session_state.current_eval_item:
        st.session_state.current_eval_item = fetch_next_item()

    target_item = st.session_state.current_eval_item

    if not target_item:
        st.info("🎉 現在評価待ち(status:0)のデータはありません！「💡 AI生成」タブで新しく作らせてください。")
        if st.button("🔄 最新の状況を確認する"):
            st.rerun()
    else:
        odai_text = target_item.get('A_TITLE', target_item.get('odai', '不明'))
        nazo_text = target_item.get('nazokake_text', target_item.get('text', ''))
        
        st.markdown(f"<div class='rlhf-box'><h4>お題：{odai_text}</h4><p style='font-size:1.2em;'>{nazo_text}</p></div>", unsafe_allow_html=True)
        
        with st.form(key=f"rlhf_form_{target_item['id']}"):
            st.markdown("### 👨‍🏫 名匠の採点と添削")
            human_score = st.slider("このAIの作品は何点？ (1: 駄作 〜 5: 傑作)", 1, 5, 3)
            human_correction = st.text_area("人間の模範解答 / 添削", placeholder="〇〇とかけて、××ととく。そのこころは、□□（同音異義語）でしょう。")
            
            if st.form_submit_button("💾 評価を記録して次の作品へ"):
                try:
                    db.collection('nazokake_evaluations').add({
                        "original_item_id": target_item['id'],
                        "A_TITLE": odai_text,
                        "nazokake_text": nazo_text,
                        "human_score": human_score,
                        "human_correction": human_correction,
                        "created_at": firestore.SERVER_TIMESTAMP
                    })
                    db.collection('nazokake_items').document(target_item['id']).update({"status": 2})
                    st.success("✅ 評価を記録しました！自動的に次の作品へ移動します...")
                    
                    st.session_state.current_eval_item = None
                    st.rerun()
                except Exception as e:
                    st.error(f"🚨 保存エラー: {e}")

elif selected_tab == "👑 殿堂入り":
    st.subheader("👑 殿堂入り (順次復旧予定)")
    st.info("旧UIのデータベース連携部分をここにマージしていきます。")

```


# ==========================================
# 📄 File: .\export_clean_context.py
# ==========================================
```py
import os

PROJECT_ROOT = "."
OUTPUT_DIR = "export_context_final"
# AIに読ませる必要のない重いフォルダ・バイナリを徹底除外
IGNORE_DIRS = {'.git', '.venv_ai', '__pycache__', 'node_modules', 'build', 'dist', OUTPUT_DIR, '.firebase', 'data', 'models'}
TARGET_EXTS = {'.py', '.js', '.html', '.css', '.json', '.md', '.rules', '.yaml', '.toml'}

os.makedirs(OUTPUT_DIR, exist_ok=True)

def generate_tree(dir_path, prefix=""):
    tree_str = ""
    try:
        entries = sorted(os.listdir(dir_path))
    except PermissionError:
        return ""
    
    entries = [e for e in entries if e not in IGNORE_DIRS and not e.startswith('.')]
    for i, entry in enumerate(entries):
        path = os.path.join(dir_path, entry)
        is_last = (i == len(entries) - 1)
        connector = "└── " if is_last else "├── "
        tree_str += f"{prefix}{connector}{entry}\n"
        if os.path.isdir(path):
            extension = "    " if is_last else "│   "
            tree_str += generate_tree(path, prefix + extension)
    return tree_str

def main():
    tree_text = "📦 PROJECT TREE (Cleaned)\n========================================\n\n" + generate_tree(PROJECT_ROOT)
    
    current_chunk = 1
    current_content = tree_text
    MAX_CHARS = 80000  # AIのコンテキスト窓に最適化
    
    def save_chunk():
        nonlocal current_chunk, current_content
        if current_content:
            out_path = os.path.join(OUTPUT_DIR, f"context_part_{current_chunk:02d}.md")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(current_content)
            print(f"  ✅ {out_path} を出力しました。")
            current_chunk += 1
            current_content = ""

    for root, dirs, files in os.walk(PROJECT_ROOT):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith('.')]
        for file in files:
            ext = os.path.splitext(file)[1].lower()
            if ext not in TARGET_EXTS:
                continue
                
            filepath = os.path.join(root, file)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    code = f.read()
                    
                ext_name = ext.replace('.', '')
                block = f"\n\n# ==========================================\n# 📄 File: {filepath}\n# ==========================================\n```{ext_name}\n{code}\n```\n"
                
                if len(current_content) + len(block) > MAX_CHARS:
                    save_chunk()
                    
                current_content += block
            except Exception as e:
                pass

    save_chunk()
    print(f"\n🎉 エクスポート完了！ '{OUTPUT_DIR}' フォルダが作成されました。")

if __name__ == "__main__":
    main()

```


# ==========================================
# 📄 File: .\export_project.py
# ==========================================
```py
import os
import math
from pathlib import Path

def get_target_dir():
    # 実行しているスクリプトと同じ場所にある "_ai_context" フォルダを指定
    root_dir = Path(__file__).parent.absolute()
    target_dir = root_dir / "_ai_context"
    return str(target_dir)

def generate_tree(dir_path, exclude_dirs, prefix=""):
    tree_str = ""
    try:
        entries = sorted(os.listdir(dir_path))
    except PermissionError:
        return ""
    
    entries = [e for e in entries if e not in exclude_dirs]
    for i, entry in enumerate(entries):
        path = os.path.join(dir_path, entry)
        is_last = (i == len(entries) - 1)
        connector = "└── " if is_last else "├── "
        tree_str += f"{prefix}{connector}{entry}\n"
        if os.path.isdir(path):
            extension = "    " if is_last else "│   "
            tree_str += generate_tree(path, exclude_dirs, prefix + extension)
    return tree_str

def export_context():
    root_dir = Path(__file__).parent.absolute()
    
    # 💡 スキャン対象とするファイルの拡張子
    target_exts = {'.py', '.json', '.md', '.txt', '.yaml', '.html', '.css', '.js'}
    
    # 💡 スキャンを除外するフォルダ（ここに書かれたフォルダはAIに送られません）
    exclude_dirs = {
        '.venv', '__pycache__', '.git', 'node_modules', 
        '.agents', '.vscode', 'data', '_ai_context',
        '_archive_tests', 'admin_scripts', 'backend-worker'
    }
    
    target_dir = get_target_dir()
    os.makedirs(target_dir, exist_ok=True)

    print(f"[{root_dir.name}] プロジェクトの構成をスキャン中...")
    
    all_lines = []

    # ==========================================
    # 1. ディレクトリツリーの生成と配列への追加
    # ==========================================
    all_lines.append("="*60)
    all_lines.append("📁 PROJECT DIRECTORY TREE")
    all_lines.append("="*60)
    # ツリーのテキストを改行ごとに分割して配列に追加
    all_lines.extend(generate_tree(str(root_dir), exclude_dirs).splitlines())
    all_lines.append("\n\n")
    
    # ==========================================
    # 2. ソースコードの収集
    # ==========================================
    print("ソースコードをスキャン中...")
    for path in root_dir.rglob('*'):
        if path.is_file() and path.suffix in target_exts:
            if not any(part in exclude_dirs for part in path.parts):
                # エクスポートスクリプト自身は出力から除外
                if path.name in ["export_project.py", os.path.basename(__file__)]:
                    continue
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        all_lines.append(f"\n\n{'='*60}")
                        all_lines.append(f"📄 File: {path.relative_to(root_dir)}")
                        all_lines.append(f"{'='*60}\n")
                        all_lines.extend(content.splitlines())
                except Exception:
                    pass

    if not all_lines:
        print("出力対象のコードが見つかりませんでした。")
        return

    # ==========================================
    # 3. ファイル構造 ＋ ソースコードの分割と保存
    # ==========================================
    # 💡 AIの読み込みエラーを防ぐための分割数（1にすれば1つのファイルにまとまります）
    split_count = 8 
    total_lines = len(all_lines)
    chunk_size = math.ceil(total_lines / split_count)
    
    print(f"全 {total_lines} 行のデータ（ファイル構成図 ＋ コード）を {split_count} 分割して出力します。\n")
    
    for i in range(split_count):
        start_idx = i * chunk_size
        end_idx = start_idx + chunk_size
        chunk_lines = all_lines[start_idx:end_idx]
        
        if not chunk_lines:
            continue
            
        out_file = os.path.join(target_dir, f"source_code_part_{i+1}.txt")
        with open(out_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(chunk_lines))
            
        print(f"✅ コード出力完了 ({i+1}/{split_count}): {out_file}")

if __name__ == "__main__":
    export_context()
```


# ==========================================
# 📄 File: .\firebase.json
# ==========================================
```json
{
  "hosting": {
    "public": "frontend/public",
    "ignore": [
      "firebase.json",
      "**/.*",
      "**/node_modules/**"
    ],
    "rewrites": [
      {
        "source": "**",
        "destination": "/index.html"
      }
    ]
  }
}

```


# ==========================================
# 📄 File: .\firestore.indexes.json
# ==========================================
```json
{
  "indexes": [
    {
      "collectionGroup": "nazokake_fewshots",
      "queryScope": "COLLECTION",
      "fields": [
        {
          "fieldPath": "__name__",
          "order": "ASCENDING"
        },
        {
          "fieldPath": "embedding",
          "vectorConfig": {
            "dimension": 768,
            "flat": {}
          }
        }
      ],
      "density": "SPARSE_ALL"
    },
    {
      "collectionGroup": "nazokake_items",
      "queryScope": "COLLECTION",
      "fields": [
        {
          "fieldPath": "status",
          "order": "ASCENDING"
        },
        {
          "fieldPath": "FINAL_SCORE_HUMAN",
          "order": "ASCENDING"
        },
        {
          "fieldPath": "__name__",
          "order": "ASCENDING"
        }
      ],
      "density": "SPARSE_ALL"
    }
  ],
  "fieldOverrides": []
}
```


# ==========================================
# 📄 File: .\firestore.rules
# ==========================================
```rules
// firestore.rules
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    
    // nazokake_items コレクションへのアクセスルール
    match /nazokake_items/{documentId} {
      
      // 【Read】誰でも読み取り可能
      allow read: if true; 

      // 【Create】フロントエンドからの新規作成(未処理データ)のみ許可
      allow create: if 
          request.resource.data.status == 0
          && request.resource.data.keys().hasAll([
               'A_TITLE', 'B_TITLE', 'C_READING', 
               'A_CONTEXT_DETAIL', 'GENERATION_TYPE', 'nazokake_text'
             ])
          && !('scores' in request.resource.data)
          && !('error_message' in request.resource.data)
          && request.resource.data.status is int;

      // 【Update / Delete】クライアントからは一切禁止（完全ブロック）
      // ※Cloud Runワーカー(Admin権限)はこれを自動でバイパスします
      allow update, delete: if false;
    }
  }
}
```


# ==========================================
# 📄 File: .\firestore_db.py
# ==========================================
```py
# firestore_db.py
import firebase_admin
from firebase_admin import credentials, firestore
import datetime
import json

def initialize_firestore():
    """Firestoreの初期化"""
    if not firebase_admin._apps:
        # ※実際のサービスアカウントキーのパスに置き換えて使用します
        try:
            cred = credentials.Certificate(".firebase/serviceAccountKey.json")
            firebase_admin.initialize_app(cred)
        except Exception as e:
            print(f"⚠️ Firestore初期化警告（ローカルテスト用）: {e}")
    return firestore.client()

def save_evaluation_result(doc_id, theme, nazokake_text, ai_evaluation_json_str):
    """
    AIの11軸評価結果と、人間の評価枠を分離してFirestoreに保存する
    """
    db = initialize_firestore()
    doc_ref = db.collection("nazokake_evaluations").document(doc_id)

    # AIが返したJSON文字列を辞書型に変換
    try:
        ai_data = json.loads(ai_evaluation_json_str)
    except json.JSONDecodeError:
        print("🚨 AIのJSON出力パースに失敗しました")
        ai_data = {}

    # Firestoreへ保存するデータ構造の構築
    save_data = {
        "theme": theme,
        "nazokake_text": nazokake_text,
        # AIによる評価データ（11軸）
        "ai_total_score": ai_data.get("ai_total_score", 0),
        "evaluation_details": ai_data.get("evaluation_details", {}),
        "judge_comment": ai_data.get("judge_comment", ""),
        # 人間による評価データ（完全に分離・初期状態はnullまたは0）
        "human_score": None, 
        "human_likes": 0,
        "created_at": firestore.SERVER_TIMESTAMP
    }

    # データの保存（マージ）
    doc_ref.set(save_data, merge=True)
    print(f"✅ Firestoreへの保存が完了しました。 [DocID: {doc_id}]")

if __name__ == "__main__":
    # テスト用モックデータ
    mock_json = """
    {
        "ai_total_score": 92,
        "evaluation_details": {
            "S_nat": 9, "S_tech": 10, "S_rhy": 8, "S_prosody": 8,
            "S_sur": 9, "S_emo": 9, "S_cultural": 10, "S_visual": 8,
            "S_sensory": 7, "S_cm": 6, "S_ontology": 8
        },
        "judge_comment": "テスト講評です。"
    }
    """
    save_evaluation_result("test_doc_001", "満員電車", "「満員電車」とかけて「寿司屋」と解く。その心は、どちらも「にぎり」が付き物です。", mock_json)

```


# ==========================================
# 📄 File: .\PROJECT_CORE.md
# ==========================================
```md
# 🏛️ NAZOKAKE-DOJO: PROJECT CORE (Single Source of Truth)

**最終更新:** 2026年6月 (Phase 3 アーキテクト純化完了版)
**アーキテクト:** Takeshi & Gem

---

## 1. システム概要 (System Overview)
本システムは、ユーザーから提供された「お題」に対して、AIが高品質な「なぞかけ」を生成し、その文化的背景・同音異義語の文脈を抽出し、11項目の独自評価軸で精密に採点（エバリュエーション）する、完全非同期型のWebアプリケーションである。

**【コア・コンセプト】**
管理者が孤独にデータを作るのではなく、一般ユーザーからの投稿や評価（道場破り）を通じてクラウドソーシングを行い、高品質なRLHF（強化学習）データを自律的に量産する「AI育成エコシステム」を構築する。

---

## 2. インフラストラクチャ・コンポーネント (Infrastructure)

### 🖥️ フロントエンド (Frontend)
* **アーキテクチャ:** 完全SPA (Single Page Application)
* **技術スタック:** HTML5 / CSS3 / Vanilla JavaScript
* **ホスティング:** Firebase Hosting
* **特徴:** `index.html` と `app_final.js` (または `app.js`) を中核とし、軽量かつ高速なレンダリングを実現。

### ⚙️ バックエンド (Backend)
* **アーキテクチャ:** RESTful API (Python 3)
* **技術スタック:** FastAPI, `httpx` (完全非同期対応)
* **ホスティング:** GCP Cloud Run (単一コンテナ統合型・ゼロスケール対応)
* **コアファイル:**
  * `backend/main.py`: エントリーポイント、CORS設定。
  * `backend/api/endpoints.py`: ルーティング、フロントエンドとのI/O接点。
  * `backend/services/ai_service.py`: デュアルAIルーティング、プロンプト構築、エラーハンドリングの本丸。

### 🗄️ データベース (Database)
* **技術スタック:** Firebase Firestore (NoSQL)
* **主要コレクション:** `nazokake_items`, `seed_odai` (お題リスト), `system_config`
* **状態管理:** `status` フィールドを用いた厳格なステートマシン（0: 初期状態, 2: 完了, -1/error: エラー等）。

---

## 3. デュアルAIアーキテクチャ (Dual-AI Engine)

推論能力とコストを最適化するため、ローカルAIとクラウドAPIをシームレスに連携させた「バケツリレー方式（フォールバック機構）」を採用。

### 🛡️ Tier 1: 高速・低コスト生成 (GCP L4要塞)
* **役割:** なぞかけの基本生成、文化背景の高速抽出。
* **環境:** 動的確保される GCP Compute Engine (g2-standard-4, L4 GPU x1)
* **エンジン:** `llama-server` 
* **モデル:** `gemma-2-9b-it-Q4_K_M.gguf` (ローカルGemma)
* **接続要件:** タイムアウト3.0秒の「フェイルファスト」設定。環境変数 `GCP_L4_IP` により動的にルーティング。

### ☁️ Tier 2: 高度推論・審査担当 (Cloud Gemini API)
* **役割:** Tier 1無応答時のフォールバック生成、および最高峰の11軸精密採点（JSON講評出力）。
* **環境:** Google Cloud GenAI API (`google-genai` SDK)
* **モデル:** `gemini-3.1-pro-preview` (評価用), `gemini-3.5-flash` (生成用)

---

## 4. MLOps & 今後のロードマップ (Roadmap)

1. **データパイプラインの完成:** Firestore上の高評価データ(status: 2)を抽出し、JSONLフォーマットでDPO/SFT学習データに変換する自動化。
2. **モデルのファインチューニング:** 抽出したデータを元に、GCP Vertex AIやColab上で独自モデルを育成。
3. **RAG（検索拡張生成）の統合:** 過去の傑作なぞかけをベクトル検索し、評価のブレ防止や生成品質の底上げを行う。

---

## 5. 絶対制約 (Architectural Guardrails)
AIエージェント、および開発者は、コード改修時に以下のルールを絶対に破ってはならない。

1. **IPハードコードの禁止:** GCP要塞のIPは必ず `.env` (GCP_L4_IP等) から取得する。
2. **完全なるエラーキャッチ (サイレント・デス撲滅):** 非同期処理 (`ai_service.py`等) で例外が発生した際は、`return`で逃げず、必ずFirestoreに `status: "error"` と理由を書き込み、無限ロードを防ぐ。
3. **Firestoreの厳格な型管理:** `orderBy`使用時の暗黙の除外（サイレント・ドロップ）を防ぐため、Timestamp型や必須フィールドの欠損を許さない。
4. **一撃必殺の原則:** 手作業でのコード置換を禁じ、パッチは常に完全な関数単位・ファイル単位のコード出力とPowerShellコマンドで行う。
5. **推測の排除:** AIはコードを書く前に必ず `Get-Content` 等で現状のファイルをダンプし、事実（ファクト）に基づいてのみ修正を行う。

```


# ==========================================
# 📄 File: .\seed_rag_database.py
# ==========================================
```py
import os
import json
import time
from pathlib import Path
from google import genai
from google.genai import types
import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

# 💡 修正1: Vectorクラスを正しい場所から直接インポート
from google.cloud.firestore_v1.vector import Vector

def seed_rag_database():
    load_dotenv()

    current_dir = Path.cwd()
    key_path = current_dir / "backend" / "serviceAccountKey.json"
    
    if not firebase_admin._apps:
        if key_path.exists():
            cred = credentials.Certificate(str(key_path))
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()
            
    db = firestore.client()
    
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("🚨 エラー: GEMINI_API_KEY が設定されていません。")
        return
        
    client = genai.Client(api_key=api_key)

    data_path = current_dir / "data" / "sft_dataset.jsonl"
    if not data_path.exists():
        print(f"🚨 エラー: {data_path} が見つかりません。")
        return

    items_to_insert = []
    with open(data_path, "r", encoding="utf-8") as f:
        for line in f:
            items_to_insert.append(json.loads(line))
            
    print(f"🚀 {len(items_to_insert)}件のデータをベクトル化し、Firestoreに登録します...")
    print("⏳ API制限(429)を回避するため、ゆっくりと処理を進めます。お茶でも飲んでお待ちください...")
    
    collection_ref = db.collection("nazokake_rag_knowledge")
    
    batch = db.batch()
    batch_count = 0
    total_inserted = 0

    for item in items_to_insert:
        prompt_text = item["messages"][0]["content"]
        start_idx = prompt_text.find("お題「") + 3
        end_idx = prompt_text.find("」で、", start_idx)
        odai = prompt_text[start_idx:end_idx] if start_idx > 2 and end_idx > -1 else prompt_text
        
        answer_text = item["messages"][1]["content"]

        # 💡 修正2: 429エラー対策（自動リトライ機能）
        success = False
        max_retries = 5
        
        for attempt in range(max_retries):
            try:
                response = client.models.embed_content(
                    model='gemini-embedding-2',
                    contents=odai,
                )
                embedding = response.embeddings[0].values
                success = True
                break # 成功したらリトライループを抜ける
                
            except Exception as e:
                error_msg = str(e)
                if '429' in error_msg or 'RESOURCE_EXHAUSTED' in error_msg:
                    # 待機時間を徐々に延ばす（5秒, 10秒, 15秒...）
                    wait_time = 5 * (attempt + 1)
                    print(f"  ⏳ 制限到達。{wait_time}秒待機して再挑戦します... (お題: {odai})")
                    time.sleep(wait_time)
                else:
                    print(f"⚠️ 予期せぬエラー (お題: {odai}): {error_msg}")
                    break # 429以外の致命的なエラーは諦める

        if not success:
            print(f"❌ リトライ上限に達したためスキップしました: {odai}")
            continue

        try:
            doc_ref = collection_ref.document()
            batch.set(doc_ref, {
                "odai": odai,
                "nazokake": answer_text,
                # 💡 修正1: 正しいVectorで包む
                "embedding": Vector(embedding)
            })
            
            batch_count += 1
            total_inserted += 1
            
            # バッチサイズを200に下げて安全にコミット
            if batch_count >= 200:
                batch.commit()
                print(f"  ... {total_inserted} 件登録完了")
                batch = db.batch()
                batch_count = 0
                
        except Exception as e:
             print(f"⚠️ 保存エラー (お題: {odai}): {e}")

        # 💡 修正2: 平常時もAPIをパンクさせないよう、0.5秒ずつ休みながら進む
        time.sleep(0.5)

    if batch_count > 0:
        batch.commit()
        print(f"  ... {total_inserted} 件登録完了")

    print(f"✅ RAGデータベースの構築が完了しました！ (合計: {total_inserted}件)")

if __name__ == "__main__":
    seed_rag_database()

```


# ==========================================
# 📄 File: .\serviceAccountKey.json
# ==========================================
```json
{
  "type": "service_account",
  "project_id": "nazokakeapp-137e5",
  "private_key_id": "a75465abf7d48f68425922f9e7b4b05c89ed95dc",
  "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC3e4BS5Qqf/+Gt\nkBJxS1k4IFMuYQSa2uA4jSovco5IpZCQ7i2bsAIIC1/4zGKYiMPYJXQQJ2hrvUTR\nOPePOY0lIvi82RDNSFeKBf9sZSJBkOzfBZUnbbP1+Vwle9TNsgni1BY2QlJmhHMC\ns05PS06EnKlhwWD0rNOelwFELMokGqbd0M+4wvZqXS3fjAE6IWKwUo88KG9LBBC5\n+XMI2HF4DdCPr5V3afNeA/0c0RhcgUAIq8EpNgI6HQl5d4M6JMr9wXYA4iOzrXwI\n5m42/EY7o2S5+EH3NRBiaQPcBjIErZaN7HMN1a55bPjm5hbtfZrgKDSO+nsiWYze\nWKjJGNsvAgMBAAECggEAIMjCbw1Zzqjr7BU4FmI+ONcdxcW0Cu9c7P3cMcooPjbH\nE/5ay9yxIDrYFR5/531YcQCQMmq4L7gL2c5x/XdtDtum0id+5w8sBQ95Sibv7gM1\nL8xRkE/7vdGmc1Qi+/X56ju3FE7ZZlP4MN1U+rob93n+keb5qf5PeaDFqybNn5GN\ntGMZdC3yOOPDYO1erWGOqhHll4ChI9ZLAExS2EpMqH6RE+ogQWNXKOFh+Dw65rau\nVnFBiGvlDN34attToqDpQLaoPKaikh7Ug7LpxpvsyXnGVqjGV6gpVy7JQHbaocQO\nufoR5pEzEpyOjrNCIjTszNliJhWIRpQM+FAbiSf4IQKBgQDvkKZ0tEmEVs+ZLzpC\nzMeHR9GyG0xuTzFS99mtYb53eNqjfLdr6hCuT+mrCckQmjqniRUL45O1VA+yYtHT\nF6dpQV6h/fARIrAIXAkiT+EvC/mFPg19gulR8uQ/h7o70hLcqKRwA/oe+vfd2r7/\nz9lGuknMLeh2P8jSdrWGhE6YVwKBgQDEEecc0KG0vHTfDAjSb56W0IJFM/YuGI/T\nhQOAeBLqlsMI/emC47YJ5IKVBej2P7oiKJaT1KpbZeulKQRANDrAAvUbCIXrBiNN\nZ+GuKNQY3Fu+VREA3tasvfSaBYFHumTZKDRLmvOHXZXqkxY9FE5CW4Nlz6dTinSq\n6ziKK+Ds6QKBgEU9q77DdRQ4+xutWMuB4JGrImK2HSss3Ha8iD/ipmhll9v06hbY\nuiWHl2QGGgUgbp+JsXmUN1cLitXmVfsLNSno6O8tNDvfqL1hzIoMSGuOrHnka4XB\nVqqG542tLxinKSh53b06iQp3QzjuRpItgwE8SqQnCK9U1DhwcxsEFqtVAoGBAIxx\nAmlaa6nJH7GwrhUFzMPcQKOPL7Qe9c6dxT9dQrd0G+mx7nRJ5Ve6rWpPHGpehVX4\nWrszJn9nRt47vga7IqXsuGKPvVT2RY0pbrbQGfRgyvpPdml4NK7xNWapsMuPELOX\nn7XUHMIGX97xUomXpOLVKA5iKkmlsCHJcOtPuMIZAoGAZwWLQLoG62T5cxi/lNla\nNm5MWUPrm1p0IUjKqLAC0yfq3oWqbMXN8Q00jDpNrX+OKlEiSvIcuMvrALmsBtpk\nLebjSZ2tyei0zYSa/yztXFmwWKVrOLSK+UHYL+RuiEnqRAvlhJevGpOYPmC+I+Yg\nSiayu6hsBtu61lXgOhn9E/U=\n-----END PRIVATE KEY-----\n",
  "client_email": "firebase-adminsdk-fbsvc@nazokakeapp-137e5.iam.gserviceaccount.com",
  "client_id": "113899526337279904827",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/firebase-adminsdk-fbsvc%40nazokakeapp-137e5.iam.gserviceaccount.com",
  "universe_domain": "googleapis.com"
}

```


# ==========================================
# 📄 File: .\skills-lock.json
# ==========================================
```json
{
  "version": 1,
  "skills": {
    "developing-genkit-dart": {
      "source": "firebase/agent-skills",
      "sourceType": "github",
      "skillPath": "skills/developing-genkit-dart/SKILL.md",
      "computedHash": "ba0025db33c95d8b66cd6de1f4c25b8b70456fb2789ec6c97cd88d432eed3fb3"
    },
    "developing-genkit-go": {
      "source": "firebase/agent-skills",
      "sourceType": "github",
      "skillPath": "skills/developing-genkit-go/SKILL.md",
      "computedHash": "5283fdc18ac5d4c4742cbf244fba1c887e04d4027e6313441ed8ff7424a88e9c"
    },
    "developing-genkit-js": {
      "source": "firebase/agent-skills",
      "sourceType": "github",
      "skillPath": "skills/developing-genkit-js/SKILL.md",
      "computedHash": "4d3de47b5be279ab3b0ee6055ae541f28d1cc45f8e8986c0b5df2f8d89f4ea30"
    },
    "developing-genkit-python": {
      "source": "firebase/agent-skills",
      "sourceType": "github",
      "skillPath": "skills/developing-genkit-python/SKILL.md",
      "computedHash": "6d80e42acbaec4f53f8f62da5d61e0ae540144552fc07fc06a3605efb5420fba"
    },
    "firebase-ai-logic-basics": {
      "source": "firebase/agent-skills",
      "sourceType": "github",
      "skillPath": "skills/firebase-ai-logic-basics/SKILL.md",
      "computedHash": "65aaefb79a4d018bb24b1904be4b9a460b189b78f26145741af83ad7c38f7669"
    },
    "firebase-app-hosting-basics": {
      "source": "firebase/agent-skills",
      "sourceType": "github",
      "skillPath": "skills/firebase-app-hosting-basics/SKILL.md",
      "computedHash": "a3ba088442abf5b97281bcf3e4dd11e1f7bdefdc5bd404b4fb30f344d19742d2"
    },
    "firebase-auth-basics": {
      "source": "firebase/agent-skills",
      "sourceType": "github",
      "skillPath": "skills/firebase-auth-basics/SKILL.md",
      "computedHash": "65e6f78dc3c9ea7896d65089899b0bd1060641b7756decd693e3179fe295456f"
    },
    "firebase-basics": {
      "source": "firebase/agent-skills",
      "sourceType": "github",
      "skillPath": "skills/firebase-basics/SKILL.md",
      "computedHash": "871b4fff9692faa25d6c9b96b8f7c2c5ea53be778bca2b702dd82ceeb8b1b272"
    },
    "firebase-crashlytics": {
      "source": "firebase/agent-skills",
      "sourceType": "github",
      "skillPath": "skills/firebase-crashlytics/SKILL.md",
      "computedHash": "e40f0b599853b0512d023306b23bfbcc39c911ff61d5f0f084cab2bce234480a"
    },
    "firebase-data-connect": {
      "source": "firebase/agent-skills",
      "sourceType": "github",
      "skillPath": "skills/firebase-data-connect-basics/SKILL.md",
      "computedHash": "506bd68146e316f296df2dd02d90aa90542584b6b131f4003447d7716155dcdd"
    },
    "firebase-firestore": {
      "source": "firebase/agent-skills",
      "sourceType": "github",
      "skillPath": "skills/firebase-firestore/SKILL.md",
      "computedHash": "49c006657db7ef1cbf6af6eb8d49c16a5a3ca7806c52e894ce0b3918d4a58ea3"
    },
    "firebase-hosting-basics": {
      "source": "firebase/agent-skills",
      "sourceType": "github",
      "skillPath": "skills/firebase-hosting-basics/SKILL.md",
      "computedHash": "0688a8ad6cb72149924352cc47e6cc8bf815e944b636a67b9da225cc9b025afc"
    },
    "firebase-security-rules-auditor": {
      "source": "firebase/agent-skills",
      "sourceType": "github",
      "skillPath": "skills/firebase-security-rules-auditor/SKILL.md",
      "computedHash": "42e793406ca8980c47fcdbd309f02838316849bcbf8475001b4ecaa6a67606b8"
    },
    "xcode-project-setup": {
      "source": "firebase/agent-skills",
      "sourceType": "github",
      "skillPath": "skills/xcode-project-setup/SKILL.md",
      "computedHash": "c212c4e08f0d2bbd4a2a61278a9a030e3da1227c0fe57022ed54d1c3c1a0aaf8"
    }
  }
}

```


# ==========================================
# 📄 File: .\backend\gemini_api.py
# ==========================================
```py
import os
import json
import traceback
from typing import Dict, Any, Optional
from pathlib import Path

import firebase_admin
from firebase_admin import credentials, firestore
from google import genai
from google.genai import types
from google.cloud.firestore_v1.vector import Vector
from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
from sentence_transformers import SentenceTransformer

# --- 初期設定 ---
current_dir = Path.cwd()
key_path = current_dir / "serviceAccountKey.json"
if not key_path.exists():
    key_path = current_dir / "backend" / "serviceAccountKey.json"

if not firebase_admin._apps:
    if key_path.exists():
        cred = credentials.Certificate(str(key_path))
        firebase_admin.initialize_app(cred)
    else:
        firebase_admin.initialize_app()
db = firestore.client()

print("🚀 [RAG Init] GLuCoSE v2 モデルをロード中...")
encoder_model = SentenceTransformer('pkshatech/GLuCoSE-base-ja-v2', trust_remote_code=True)
print("✅ [RAG Init] モデルロード完了")

def get_rag_context(odai: str) -> str:
    """指定されたお題に基づき、Firestoreから関連する参考データを取得する。"""
    try:
        query_vector = encoder_model.encode([odai])[0].tolist()
        collection_ref = db.collection("nazokake_rag_knowledge")
        
        results = collection_ref.find_nearest(
            vector_field="embedding",
            query_vector=Vector(query_vector),
            distance_measure=DistanceMeasure.COSINE,
            limit=3
        ).stream()

        rag_text = ""
        count = 0
        for doc in results:
            data = doc.to_dict()
            count += 1
            rag_text += f"[参考例 {count}] お題: {data.get('odai')}\nなぞかけ: {data.get('nazokake')}\n\n"
            
        if count == 0:
            return "※参考データなし"
        return rag_text
    except Exception as e:
        print(f"⚠️ [RAG Error] ベクトル検索中にエラー発生: {e}")
        return "※参考データ取得エラー"

def run_gemini_evaluation(item_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Gemini APIを使用して、なぞかけを多角的な指標で評価する。"""
    try:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("環境変数 GEMINI_API_KEY が設定されていません")
            
        client = genai.Client(api_key=api_key)
        odai = data.get("A_TITLE", "")
        nazokake_text = data.get("nazokake_text", "")
        
        if not odai or not nazokake_text:
            raise ValueError("評価に必要なデータが不足しています")

        print(f"🔍 [Eval] ID: {item_id} (お題: {odai}) の評価を開始...")
        rag_context = get_rag_context(odai)
        print(f"📚 [RAG Info] 取得した過去の傑作コンテキスト:\n{rag_context}")

        prompt = f'''
あなたは、なぞかけの美しさと面白さを極めた「最高峰の審査員（AI落語家）」です。
以下の「評価対象のなぞかけ」を、11の学術的指標に基づき、0.0〜1.0の範囲で厳密にスコアリングしてください。

【評価の参考データ（過去の似たお題の傑作）】
以下のなぞかけは、過去に人間が高く評価した「お手本（正解）」のデータです。
これを基準（アンカー）として、今回の作品の「意味の遠さ」や「オチの美しさ」を相対的に比較・採点してください。
---
{rag_context}
---

【評価対象のなぞかけ】
お題: {odai}
作品: {nazokake_text}

【出力ルール】
必ず以下のJSON形式（スキーマ）のみを出力してください。Markdownの装飾（`json）は絶対に含めないでください。

{{
  "reasoning": "全体の講評や、参考データと比較した際の優れた点・劣る点を簡潔に記述してください",
  "S_sur": 0.0,
  "S_nat": 0.0,
  "S_tech": 0.0,
  "S_emo": 0.0,
  "S_rhy": 0.0,
  "S_sensory": 0.0,
  "S_visual": 0.0,
  "S_ontology": 0.0,
  "S_cultural": 0.0,
  "S_cm": 0.0,
  "S_prosody": 0.0,
  "S_total": 0.0
}}
'''

        response = client.models.generate_content(
            model='gemini-3-flash-preview',
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2,
                response_mime_type="application/json"
            )
        )
        
        result_text = response.text.strip()
        # LLMが出力する可能性のあるMarkdownのコードブロック装飾を削除
        if result_text.startswith("`json"):
            result_text = result_text[7:]
        if result_text.endswith("`"):
            result_text = result_text[:-3]
            
        evaluation_result = json.loads(result_text)
        print(f"✅ [Eval Success] ID: {item_id} の評価が完了しました")
        return evaluation_result

    except Exception as e:
        print(f"❌ [Eval Error] ID: {item_id} の評価中にエラー: {e}")
        traceback.print_exc()
        return None
```


# ==========================================
# 📄 File: .\backend\main.py
# ==========================================
```py
import os
from dotenv import load_dotenv
load_dotenv()  # .envファイルからAPIキーを読み込む

import firebase_admin

if not firebase_admin._apps:
    firebase_admin.initialize_app()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api import endpoints

app = FastAPI(title="なぞかけディスカバリー API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:3001", "http://127.0.0.1:3001", "https://nazokakeapp-137e5.web.app", "https://nazokakeapp-137e5.firebaseapp.com"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(endpoints.router, prefix="/api")

@app.get("/")
async def root():
    return {"message": "Nazokake Backend is running on Cloud Run!"}


```


# ==========================================
# 📄 File: .\backend\api\endpoints.py
# ==========================================
```py
import os
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, Header, HTTPException, Request
env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))
load_dotenv(dotenv_path=env_path)
from datetime import datetime, timezone, timedelta
import firebase_admin
from firebase_admin import firestore
from models.schemas import EvaluateRequest, HumanSubmitRequest, GenerateRequest
from pydantic import BaseModel

class SystemSettings(BaseModel):
    temperature: float
    model_name: str
    system_prompt: str
from services.ai_service import evaluate_and_update_task, generate_nazokake
import random
from functools import wraps
from typing import Callable, Any
import asyncio
import inspect

router = APIRouter()

def serialize_doc(doc) -> dict:
    data = doc.to_dict()
    data["doc_id"] = doc.id
    if "timestamp" in data and isinstance(data["timestamp"], datetime):
        data["timestamp"] = str(data["timestamp"])
    return data

def handle_exceptions(func: Callable) -> Callable:
    if inspect.iscoroutinefunction(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs) -> Any:
            try:
                return await func(*args, **kwargs)
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")
        return async_wrapper
    else:
        @wraps(func)
        def sync_wrapper(*args, **kwargs) -> Any:
            try:
                return func(*args, **kwargs)
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")
        return sync_wrapper

async def generate_and_update_task(doc_id: str, odai: str):

    try:
        parsed_result = await generate_nazokake(odai)
        toku = parsed_result.get("toku", "")
        kokoro = parsed_result.get("kokoro", "")
        nazokake_text = f"「{odai}」とかけて、「{toku}」と解く。\nその心は、「{kokoro}」"
        
        await asyncio.to_thread(
            admin_db.collection("nazokake_items").document(doc_id).update,
            {"result": parsed_result, "message": "鑑定機関に評価を依頼中..."}
        )
        await evaluate_and_update_task(admin_db, doc_id, odai, nazokake_text)
    except Exception as e:
        await asyncio.to_thread(
            admin_db.collection("nazokake_items").document(doc_id).update,
            {"status": "error", "message": f"処理中にエラーが発生しました: {str(e)}"}
        )

def _fetch_valid_items(limit: int = 200, order_by_desc: bool = False) -> list[dict]:

    query = admin_db.collection("nazokake_items")
    if order_by_desc:
        query = query.order_by("timestamp", direction=firestore.Query.DESCENDING)
    raw_docs = query.limit(limit).stream()
    valid_docs = [d for d in raw_docs if d.to_dict().get("status", "completed") == "completed"]
    return [serialize_doc(d) for d in valid_docs]

@router.get("/feed")
@handle_exceptions
def get_feed():
    all_items = _fetch_valid_items(limit=200)
    items_to_process = all_items[:50]
    random_items = random.sample(items_to_process, min(10, len(items_to_process)))
    scored_items = []
    for item in items_to_process:
        evals = item.get("user_evaluations", [])
        human_evals = [e.get("user_score", 0) for e in evals if not e.get("is_synthetic")]
        if human_evals:
            avg = sum(human_evals) / len(human_evals)
            scored_items.append((avg, item))
    scored_items.sort(key=lambda x: x[0], reverse=True)
    top10 = [item for avg, item in scored_items[:10]]
    golden = [item for avg, item in scored_items if avg >= 4.5]
    return {"top10": top10, "random": random_items, "golden": golden}

@router.get("/dojo_arena")
@handle_exceptions
def get_dojo_arena():
    all_items = _fetch_valid_items(limit=300, order_by_desc=True)
    items_to_process = all_items[:100]
    arena_items = random.sample(items_to_process, min(30, len(items_to_process)))
    return {"arena_items": arena_items}

@router.post("/submit_human")
@handle_exceptions
async def submit_human(req: HumanSubmitRequest):

    doc_ref = admin_db.collection("nazokake_items").document()
    doc_ref.set({
        "A_TITLE": req.odai,
        "nazokake_text": req.nazokake_text,
        "author": "Human",
        "parent_id": req.parent_id,
        "is_sft_data": bool(req.parent_id),
        "timestamp": firestore.SERVER_TIMESTAMP,
        "status": "processing",
        "eval_status": "processing",
        "s_total": 0.0
    })
    await evaluate_and_update_task(admin_db, doc_ref.id, req.odai, req.nazokake_text)
    return {"status": "processing", "doc_id": doc_ref.id}

@router.get("/status/{doc_id}")
@handle_exceptions
def get_status(doc_id: str):
    doc = admin_db.collection("nazokake_items").document(doc_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Document not found")
    data = serialize_doc(doc)
    return {
        "status": data.get("status", "unknown"),
        "eval_status": data.get("eval_status", "unknown"),
        "message": data.get("message", ""),
        "result": data.get("result", {}),
        "scores": data.get("scores", {}),
        "reasoning": data.get("reasoning", ""),
        "s_total": data.get("s_total", 0.0)
    }

@router.post("/evaluate")
@handle_exceptions
def evaluate_item(req: EvaluateRequest):
    doc_ref = admin_db.collection("nazokake_items").document(req.doc_id)
    eval_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_score": req.user_score,
        "is_synthetic": False,
        "source": "human_web_ui"
    }
    doc_ref.update({"user_evaluations": firestore.ArrayUnion([eval_data])})
    return {"status": "success"}

@router.post("/generate")
@handle_exceptions
async def generate_ai(req: GenerateRequest):

    doc_ref = admin_db.collection("nazokake_items").document()
    doc_ref.set({
        "odai": req.odai,
        "status": "processing",
        "message": "AIがなぞかけを生成中...",
        "timestamp": firestore.SERVER_TIMESTAMP,
    })
    await generate_and_update_task(doc_ref.id, req.odai)
    return {"status": "processing", "task_id": doc_ref.id, "message": "お題を受け付けました..."}

# 🧟‍♂️ [新規追加] ゾンビデータ駆除（自己修復）エンドポイント
@router.post("/maintenance/cleanup_zombies")
@handle_exceptions
async def cleanup_zombies():

    # 5分以上「processing」のまま放置されているドキュメントを検索
    threshold_time = datetime.now(timezone.utc) - timedelta(minutes=5)
    query = admin_db.collection("nazokake_items").where("status", "==", "processing").where("timestamp", "<", threshold_time)
    
    zombies = query.stream()
    cleaned_count = 0
    for doc in zombies:
        doc.reference.update({
            "status": "error",
            "message": "処理がタイムアウトしました。AIエンジン（GCP要塞）が起動していない可能性があります。"
        })
        cleaned_count += 1
        
    return {"status": "success", "cleaned_zombies": cleaned_count, "message": f"{cleaned_count}件のゾンビデータを修復しました。"}

# ==========================================
# 🛡️ 管理者コンソール (RLHF) 用エンドポイント
# ==========================================
from pydantic import BaseModel
from google.cloud.firestore_v1.base_query import FieldFilter
from google.cloud import firestore

# 🌍 グローバルDBクライアント（最速初期化）
admin_db = firestore.Client()

# ==========================================
# 🛡️ 認証ゲートウェイ (Cockpit Security)
# ==========================================
ADMIN_USER_ENV = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS_ENV = os.getenv("ADMIN_PASS", "password")

def verify_admin(x_admin_user: str = Header(None), x_admin_pass: str = Header(None)):
    if not x_admin_user or not x_admin_pass:
        raise HTTPException(status_code=401, detail="認証情報がありません")
    if x_admin_user != ADMIN_USER_ENV or x_admin_pass != ADMIN_PASS_ENV:
        raise HTTPException(status_code=401, detail="認証情報が一致しません")
    return True



from fastapi import HTTPException

class AdminApproveRequest(BaseModel):
    odai: str
    toku: str
    kokoro: str
    s_total: float
    is_golden: bool
    tier: float = 1.5

@router.get("/admin/feed")
async def get_admin_feed(is_admin: bool = Depends(verify_admin)):
    try:
        # DBへの負荷を下げるためPython側でフィルタリング
        docs = admin_db.collection("nazokake_items").where(filter=FieldFilter("status", "==", 2)).limit(50).stream()
        items = []
        for doc in docs:
            data = doc.to_dict()
            # 🌟 ユーザーが道場破り済み かつ 管理者がまだ承認していないデータのみ抽出
            if data.get("is_user_edited") and not data.get("is_golden_data"):
                data["id"] = doc.id
                items.append(data)
        return {"items": items}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/admin/approve/{doc_id}")
async def approve_admin_item(doc_id: str, req: AdminApproveRequest, request: Request, is_admin: bool = Depends(verify_admin)):
    try:
        # 修正: Requestオブジェクトを引数に追加し、重複していたブロック処理を一本化
        client_ip = request.client.host if request.client else "unknown"
        banned_doc = admin_db.collection("banned_ips").document(client_ip).get()
        if banned_doc.exists:
            raise HTTPException(status_code=403, detail="このIPアドレスからのアクセスは制限されています。")
        doc_ref = admin_db.collection("nazokake_items").document(doc_id)
        # 修正されたテキストを綺麗なフォーマットで再構築
        fixed_text = f"「{req.odai}」とかけて、「{req.toku}」と解く。その心は、{req.kokoro}"
        
        update_data = {
            "A_TITLE": req.odai,
            "result": {"toku": req.toku, "kokoro": req.kokoro}, # 分離して保存
            "total_score": req.s_total, # 古いキー名も
            "s_total": req.s_total,     # 新しいキー名も両方更新
            "nazokake_text": fixed_text,
            "human_comment": req.human_comment,
            "is_reviewed_by_admin": True,
            "is_golden_data": req.is_golden,
            "status": req.tier
        }
        
        doc_ref.set(update_data, merge=True)
        return {"message": "Success", "doc_id": doc_id, "is_golden": req.is_golden}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class UserEvaluateRequest(BaseModel):
    odai: str
    toku: str
    kokoro: str
    s_total: float
    human_comment: str = ""

@router.get("/feed/items")
async def get_user_feed():
    try:
        docs = admin_db.collection("nazokake_items").where(filter=FieldFilter("status", "==", 2)).limit(30).stream()
        items = []
        for doc in docs:
            data = doc.to_dict()
            # 誰も手をつけていないピュアなAI生データだけをユーザーに表示
            if not data.get("is_user_edited") and not data.get("is_golden_data"):
                data["id"] = doc.id
                items.append(data)
        return {"items": items}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/feed/evaluate/{doc_id}")
async def evaluate_user_item(doc_id: str, req: UserEvaluateRequest, request: Request):
    try:
        # 修正: client_ipを明示的に取得し、NameError(500エラー)を完全に防止
        client_ip = request.client.host if request.client else "unknown"

        doc_ref = admin_db.collection("nazokake_items").document(doc_id)
        fixed_text = f"「{req.odai}」とかけて、「{req.toku}」と解く。その心は、{req.kokoro}"
        update_data = {
            "A_TITLE": req.odai,
            "result": {"toku": req.toku, "kokoro": req.kokoro},
            "total_score": req.s_total,
            "s_total": req.s_total,
            "nazokake_text": fixed_text,
            "human_comment": req.human_comment,
            "is_user_edited": True,  # 🌟 管理者コクピットへ送るためのフラグ
            "submitter_ip": client_ip
        }
        doc_ref.set(update_data, merge=True)
        return {"message": "Success", "doc_id": doc_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ==========================================
# 🛡️ 管理者用: 荒らしIPブロックAPI
# ==========================================
class BanRequest(BaseModel):
    ip_address: str
    reason: str = "Spam"

@router.post("/admin/ban_ip")
async def ban_ip_address(req: BanRequest, is_admin: bool = Depends(verify_admin)):
    try:
        admin_db.collection("banned_ips").document(req.ip_address).set({
            "reason": req.reason
        })
        return {"message": f"IP {req.ip_address} をブラックリストに登録しました。"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ==========================================
# 🎛️ 管理者用: AIエンジン設定API
# ==========================================
@router.post("/admin/settings")
async def save_system_settings(req: SystemSettings, is_admin: bool = Depends(verify_admin)):
    try:
        admin_db.collection("system_configs").document("ai_settings").set({
            "temperature": req.temperature,
            "model_name": req.model_name,
            "system_prompt": req.system_prompt,
            "updated_at": firestore.SERVER_TIMESTAMP
        })
        return {"message": "AIエンジンの設定を保存しました。"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/admin/settings")
async def get_system_settings(is_admin: bool = Depends(verify_admin)):
    try:
        doc = admin_db.collection("system_configs").document("ai_settings").get()
        if doc.exists:
            return doc.to_dict()
        return {"temperature": 0.7, "model_name": "gemini-1.5-flash", "system_prompt": "あなたは前衛的な天才なぞかけ芸人です。"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class AdminDocRequest(BaseModel):
    doc_id: str

@router.post("/admin/delete")
async def delete_admin_item(req: AdminDocRequest, is_admin: bool = Depends(verify_admin)):
    try:
        admin_db.collection("nazokake_items").document(req.doc_id).delete()
        return {"message": "データをDBから完全に抹殺しました。"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/admin/reset_eval/{doc_id}")
async def reset_eval_item(doc_id: str, request: Request, is_admin: bool = Depends(verify_admin)):
    try:
        doc_ref = admin_db.collection("nazokake_items").document(doc_id)
        doc_ref.update({
            "human_comment": firestore.DELETE_FIELD,
            "is_user_edited": False,
            "is_reviewed_by_admin": False,
            "status": 1
        })
        return {"message": "人間の評価を白紙に戻し、再評価待ちにしました。"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

```


# ==========================================
# 📄 File: .\backend\api\evaluate.py
# ==========================================
```py

```


# ==========================================
# 📄 File: .\backend\api\__init__.py
# ==========================================
```py

```


# ==========================================
# 📄 File: .\backend\core\config.py
# ==========================================
```py
import os
import json
from dotenv import load_dotenv

# 現在のファイルディレクトリを取得
current_dir = os.path.dirname(os.path.abspath(__file__))
# 親ディレクトリ（backend/）を取得
backend_dir = os.path.dirname(current_dir)

# .env ファイルのパスを構築し、環境変数をロード
env_path = os.path.join(backend_dir, '.env')
load_dotenv(dotenv_path=env_path)

# 環境変数からAPIキーとモデル名を読み込む
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
EVALUATOR_MODEL_NAME = os.environ.get("EVALUATOR_MODEL_NAME", "gemini-3-flash-preview")

# Firebase認証ファイルパス
FIREBASE_CRED_PATH = "serviceAccountKey.json"

# prompt_config.json の読み込み
config_path = os.path.join(current_dir, "prompt_config.json")
try:
    with open(config_path, "r", encoding="utf-8") as f:
        PROMPT_CONFIG = json.load(f)
except Exception as e:
    print(f"🚨 prompt_config.json load error: {e}")
    PROMPT_CONFIG = {"system_instruction": "", "weights": {"default": 1.0}}
```


# ==========================================
# 📄 File: .\backend\core\prompt_config.json
# ==========================================
```json
{
  "system_instruction": "あなたはプロの『なぞかけ』審査員であり、言語学と認知科学の専門家です。以下の12軸のルーブリックに従い、入力されたお題と解の構造を深く分析し、評価を行ってください。\n\n【評価ルーブリック（一部抜粋）】\n- S_sur (意外性): お題と解の『意味的跳躍距離』。単なる同音異義語(0.4)。全く異なる概念が鮮やかに結びつく場合(0.8以上)。\n- S_tech (技巧性): 掛詞の複雑さ。単純な一致(0.3)、二段落ち・長い文字列の完全一致(0.8以上)。\n- S_ontology (存在論): 物理的・抽象的カテゴリーの越境度合い。\n\n【出力フォーマット】\n必ず以下のJSON形式で出力してください。最初に <thinking> キーの中で思考の連鎖（CoT）を行い、掛詞の分解と評価理由を言語化してから、最終スコア（0.0〜1.0）を出力すること。\n\n{\n  \"thinking\": \"お題『〇〇』と解『〇〇』の分析。掛詞は『〇〇』。S_surは〜という理由で0.8とする...\",\n  \"scores\": {\n    \"S_humor\": 0.8,\n    \"S_sur\": 0.7,\n    \"S_tech\": 0.9\n  }\n}",
  "weights": {
    "S_humor": 1.5,
    "S_tech": 1.5,
    "S_emo": 1.5,
    "S_sur": 1.2,
    "default": 1.0
  }
}
```


# ==========================================
# 📄 File: .\backend\core\__init__.py
# ==========================================
```py

```


# ==========================================
# 📄 File: .\backend\services\ai_service.py
# ==========================================
```py
import json
import os
import re
import asyncio
import httpx
from firebase_admin import firestore
from google import genai
from google.genai.types import GenerateContentConfig

# --- 設定 ---
# 修正: IPのハードコードを完全排除。環境変数が無い場合は空文字にする
VM_IP = os.environ.get("GCP_L4_IP", "")
TIER1_URL = f"http://{VM_IP}:8080/v1/chat/completions" if VM_IP else ""
TIER2_URL = f"http://{VM_IP}:8081/v1/chat/completions" if VM_IP else ""

EVALUATOR_MODEL = os.environ.get("EVALUATOR_MODEL_NAME", "gemini-3.1-pro-preview")
GENERATOR_FALLBACK = os.environ.get("GENERATOR_FALLBACK_MODEL", "gemini-3.5-flash")

# 修正: VM_IPが未設定の場合は、強制的にローカルGCP通信を無効化（通信エラーによるサイレントデス回避）
_use_local = os.environ.get("USE_LOCAL_GCP", "false").lower() == "true"
USE_LOCAL_GCP = _use_local and bool(VM_IP)

async def chat_completion_local(url, system_prompt, user_prompt, max_tokens=256, temperature=0.8):
    if not url:
        raise ValueError("VM_IPが設定されていません。")
    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": 0.9
    }
    # 修正: GCP要塞へのフェイルファスト（3秒で諦める）- 維持
    async with httpx.AsyncClient(timeout=3.0) as client:
        res = await client.post(url, json=payload)
        res.raise_for_status()
        return res.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()

async def generate_nazokake(odai: str) -> dict:
    """お題を受け取り、必ず規定のJSONフォーマットで辞書を返す"""
    
    # ==========================================
    # 🚀 動的設定のフェッチ (自律型ロジック)
    # ==========================================
    db = firestore.client()
    dyn_temp = 0.8
    dyn_model = GENERATOR_FALLBACK
    dyn_persona = "あなたは前衛的な天才なぞかけ芸人です。"
    
    try:
        config_doc = db.collection("system_configs").document("ai_settings").get()
        if config_doc.exists:
            c_data = config_doc.to_dict()
            dyn_temp = float(c_data.get("temperature", 0.8))
            dyn_model = c_data.get("model_name", GENERATOR_FALLBACK)
            dyn_persona = c_data.get("system_prompt", dyn_persona)
    except Exception as e:
        print(f"⚠️ 動的設定の取得に失敗しました。デフォルト値を使用します: {e}")

    # 動的に取得したペルソナ（プロンプト）と、JSON出力の絶対制約を結合
    sys_prompt = f"""{dyn_persona}
【重要】提供される例は「型」の参考のみとし、言葉や内容は絶対にコピーせず100%オリジナルの発想で出力してください。

【思考プロセス】
1. お題(A)から連想される言葉を挙げる。
2. その言葉と同じ「ひらがな」で、全く別の意味を持つ言葉(B)を探す。
3. (B)から連想される言葉を「とく(××)」にする。
【絶対制約】「××ととく」の「××」は絶対に10文字以内の短い単語にしてください。

【出力フォーマット】
必ず以下のJSONフォーマット【のみ】で出力してください。Markdown装飾（```jsonなど）は絶対に使用しないでください。
{{
  "hint": "AIの思考プロセス、連想したことの解説",
  "toku": "短い単語（例：打率）",
  "kokoro": "落ちの文章（例：どちらもヒットが求められるでしょう）"
}}"""
    
    user_prompt = f"お題「{odai}」でなぞかけを作成し、JSONフォーマットで出力してください。"
    
    raw_result = ""
    if USE_LOCAL_GCP:
        try:
            print(f"🔍 GCP要塞へ接続を試みます... (Temp: {dyn_temp})")
            raw_result = await chat_completion_local(TIER1_URL, sys_prompt, user_prompt, max_tokens=250, temperature=dyn_temp)
        except Exception as conn_err_1:
            print(f"⚠️ GCP要塞が無応答({conn_err_1})。フォールバックします。")
    
    if not raw_result:
        print(f"☁️ クラウドGeminiで生成します... (Model: {dyn_model}, Temp: {dyn_temp})")
        client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
        full_prompt = f"{sys_prompt}\n\n{user_prompt}"
        res_create = await client.aio.models.generate_content(
            model=dyn_model, 
            contents=full_prompt, 
            config=GenerateContentConfig(response_mime_type="application/json", temperature=dyn_temp)
        )
        raw_result = res_create.text
        
    try:
        cleaned_result = re.sub(r'```json\n?|```\n?', '', raw_result).strip()
        match = re.search(r'\{.*\}', cleaned_result, re.DOTALL)
        if match: 
            return json.loads(match.group(0))
        else: 
            return json.loads(cleaned_result)
    except Exception as e:
        print(f"解析エラー: {e}")
        return {"hint": "AIの思考(JSONパース失敗)", "toku": raw_result[:20], "kokoro": raw_result}
async def evaluate_and_update_task(db, doc_id: str, odai: str, nazokake_text: str):
    """なぞかけの文章を評価し、11項目のスコアと講評をDBに上書きする"""
    doc_ref = db.collection("nazokake_items").document(doc_id)
    try:
        # 同期ライブラリ(firebase_admin)のI/Oでイベントループを止めないための安全策
        doc = await asyncio.to_thread(doc_ref.get)
        if doc.exists and doc.to_dict().get("eval_status") == "completed": 
            return
        
        ctx_sys = "あなたは日本の現代カルチャーに精通したエージェントです。事実と文脈だけを簡潔に出力してください。"
        ctx_user = f"お題「{odai}」となぞかけ「{nazokake_text}」の同音異義語と文化的背景を解説してください。"
        context_text = ""
        
        if USE_LOCAL_GCP:
            try:
                print("🔍 GCP要塞で文化背景の抽出を試みます...")
                context_text = await chat_completion_local(TIER2_URL, ctx_sys, ctx_user, max_tokens=300, temperature=0.3)
            except Exception as conn_err_2:
                print(f"⚠️ 文化背景抽出スキップ: {conn_err_2}")
                
        if not context_text: 
            context_text = "※直通モードのため文化背景の自動抽出なし"

        judge_sys = "あなたは最高峰の採点AIシステムです。\n以下の11項目の評価軸（0.0〜1.0）でなぞかけを評価し、結果をJSONフォーマット【のみ】で出力してください。Markdown装飾は絶対に使用しないでください。\n\n{\n  \"scores\": {\n    \"S_sur\": 0.0, \"S_tech\": 0.0, \"S_emo\": 0.0, \"S_rhy\": 0.0, \"S_sensory\": 0.0, \n    \"S_visual\": 0.0, \"S_ontology\": 0.0, \"S_cultural\": 0.0, \"S_cm\": 0.0, \"S_prosody\": 0.0, \"S_nat\": 0.0\n  },\n  \"reasoning\": \"ここに200文字以内で講評を記述\"\n}"
        judge_user = f"以下のなぞかけと文化背景を元に、JSONフォーマットのみで評価を出力してください。\n\n【なぞかけ】\n{nazokake_text}\n\n【文化背景】\n{context_text}\n\n結果（JSONのみ）:"
        raw_result = ""
        
        if USE_LOCAL_GCP:
            try:
                print("🔍 GCP要塞で評価を試みます...")
                raw_result = await chat_completion_local(TIER2_URL, judge_sys, judge_user, max_tokens=600, temperature=0.1)
            except Exception as conn_err_3:
                print(f"⚠️ 評価スキップ: {conn_err_3}")
                
        if not raw_result:
            print("☁️ クラウドGeminiで評価します...")
            client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
            full_judge_prompt = f"{judge_sys}\n\n{judge_user}"
            res_eval = await client.aio.models.generate_content(
                model=EVALUATOR_MODEL, 
                contents=full_judge_prompt, 
                config=GenerateContentConfig(response_mime_type="application/json", temperature=0.1)
            )
            raw_result = res_eval.text

        eval_data = {}
        try:
            cleaned_result = re.sub(r'```json\n?|```\n?', '', raw_result).strip()
            match = re.search(r'\{.*\}', cleaned_result, re.DOTALL)
            if match: 
                eval_data = json.loads(match.group(0))
            else: 
                raise ValueError("JSON形式が見つかりません")
        except Exception as parse_err:
            await asyncio.to_thread(doc_ref.update, {"status": "error", "eval_status": "error", "message": f"AIの評価フォーマットエラー: {parse_err}"})
            return 

        scores = eval_data.get("scores", {})
        final_scores = {k: float(scores.get(k, 0.5)) for k in ["S_sur", "S_tech", "S_emo", "S_rhy", "S_sensory", "S_visual", "S_ontology", "S_cultural", "S_cm", "S_prosody", "S_nat"]}
        s_total = (sum(final_scores.values()) / 11.0) * 5.0

        await asyncio.to_thread(doc_ref.update, {
            "eval_status": "completed", 
            "status": "completed", 
            "context_extracted": context_text, 
            "scores": final_scores, 
            "s_total": s_total, 
            "reasoning": eval_data.get("reasoning", "講評が取得できませんでした。"), 
            "message": "生成・鑑定が完了しました！",
            "evaluated_at": firestore.SERVER_TIMESTAMP
        })
    except Exception as e:
        # 修正: どんな予期せぬエラーでも絶対にDBにエラー状態を書き込み、無限ロードを防ぐ Guardrails
        await asyncio.to_thread(doc_ref.update, {"status": "error", "eval_status": "error", "message": f"システムエラー: {str(e)}"})

```


# ==========================================
# 📄 File: .\backend\services\__init__.py
# ==========================================
```py

```


# ==========================================
# 📄 File: .\frontend\analysis_options.yaml
# ==========================================
```yaml
# This file configures the analyzer, which statically analyzes Dart code to
# check for errors, warnings, and lints.
#
# The issues identified by the analyzer are surfaced in the UI of Dart-enabled
# IDEs (https://dart.dev/tools#ides-and-editors). The analyzer can also be
# invoked from the command line by running `flutter analyze`.

# The following line activates a set of recommended lints for Flutter apps,
# packages, and plugins designed to encourage good coding practices.
include: package:flutter_lints/flutter.yaml

linter:
  # The lint rules applied to this project can be customized in the
  # section below to disable rules from the `package:flutter_lints/flutter.yaml`
  # included above or to enable additional rules. A list of all available lints
  # and their documentation is published at https://dart.dev/lints.
  #
  # Instead of disabling a lint rule for the entire project in the
  # section below, it can also be suppressed for a single line of code
  # or a specific dart file by using the `// ignore: name_of_lint` and
  # `// ignore_for_file: name_of_lint` syntax on the line or in the file
  # producing the lint.
  rules:
    # avoid_print: false  # Uncomment to disable the `avoid_print` rule
    # prefer_single_quotes: true  # Uncomment to enable the `prefer_single_quotes` rule

# Additional information about this file can be found at
# https://dart.dev/guides/language/analysis-options

```


# ==========================================
# 📄 File: .\frontend\firebase.json
# ==========================================
```json
{"flutter":{"platforms":{"android":{"default":{"projectId":"nazokakeapp-137e5","appId":"1:862686676938:android:6ae8c7aba66bd2e4e6f133","fileOutput":"android/app/google-services.json"}},"dart":{"lib/firebase_options.dart":{"projectId":"nazokakeapp-137e5","configurations":{"android":"1:862686676938:android:6ae8c7aba66bd2e4e6f133","ios":"1:862686676938:ios:b52c909dc3b56482e6f133","macos":"1:862686676938:ios:b52c909dc3b56482e6f133","web":"1:862686676938:web:64489be095f5102ee6f133","windows":"1:862686676938:web:7ca106d70a11d87de6f133"}}}}}}
```


# ==========================================
# 📄 File: .\frontend\hard_reset.py
# ==========================================
```py
import os
import sys

# 1. 不要なファイルを削除し、ダミー画面を1つに統合
dummy_code = """import 'package:flutter/material.dart';

class DummyScreen extends StatelessWidget {
  final String title;
  const DummyScreen({super.key, required this.title});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(title)),
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.construction, size: 64, color: Colors.grey),
            const SizedBox(height: 16),
            Text('$title機能は現在開発中です！', style: const TextStyle(fontSize: 18, color: Colors.grey)),
          ],
        ),
      ),
    );
  }
}
"""
with open("lib/screens/dummy_screens.dart", "w", encoding="utf-8") as f:
    f.write(dummy_code)

# 2. 10:00時点の4タブ構成の main_tab_screen.dart を復元
tab_code = """import 'package:flutter/material.dart';
import 'home_screen.dart';
import 'dummy_screens.dart';

class MainTabScreen extends StatefulWidget {
  const MainTabScreen({super.key});

  @override
  State<MainTabScreen> createState() => _MainTabScreenState();
}

class _MainTabScreenState extends State<MainTabScreen> {
  int _currentIndex = 0;

  final List<Widget> _screens = [
    const HomeScreen(),
    const DummyScreen(title: '自作鑑定'),
    const DummyScreen(title: '評価して育てる'),
    const DummyScreen(title: '楽しみ方'),
  ];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: IndexedStack(
        index: _currentIndex,
        children: _screens,
      ),
      bottomNavigationBar: BottomNavigationBar(
        currentIndex: _currentIndex,
        onTap: (index) => setState(() => _currentIndex = index),
        type: BottomNavigationBarType.fixed,
        selectedItemColor: const Color(0xFF902A19),
        unselectedItemColor: Colors.grey,
        selectedFontSize: 12,
        unselectedFontSize: 12,
        items: const [
          BottomNavigationBarItem(icon: Icon(Icons.lightbulb), label: 'AI生成'),
          BottomNavigationBarItem(icon: Icon(Icons.draw), label: '自作鑑定'),
          BottomNavigationBarItem(icon: Icon(Icons.receipt_long), label: '評価して育てる'),
          BottomNavigationBarItem(icon: Icon(Icons.help_outline), label: '楽しみ方'),
        ],
      ),
    );
  }
}
"""
with open("lib/screens/main_tab_screen.dart", "w", encoding="utf-8") as f:
    f.write(tab_code)

# 3. 10:00時点の美しい home_screen.dart を復元
home_code = """import 'package:flutter/material.dart';
import '../services/nazokake_api_service.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final TextEditingController _odaiController = TextEditingController();
  final NazokakeApiService _apiService = NazokakeApiService();
  Stream<NazokakeState>? _taskStream;
  bool _isGenerating = false;

  void _startGeneration() {
    final odai = _odaiController.text.trim();
    if (odai.isEmpty) return;
    FocusScope.of(context).unfocus();
    setState(() {
      _isGenerating = true;
      _taskStream = _apiService.generateNazokake(odai);
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('⛩ 謎掛け学術振興会')),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          children: [
            Card(
              elevation: 2,
              color: Colors.white,
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
              child: Padding(
                padding: const EdgeInsets.all(24.0),
                child: Column(
                  children: [
                    const Text('AIに謎掛けを作らせる', style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: Color(0xFF902A19))),
                    const SizedBox(height: 24),
                    TextField(
                      controller: _odaiController,
                      decoration: InputDecoration(
                        labelText: 'お題を入力 (例: 大谷翔平)',
                        border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
                        filled: true,
                        fillColor: Colors.grey[50],
                      ),
                      enabled: !_isGenerating,
                    ),
                    const SizedBox(height: 24),
                    SizedBox(
                      width: double.infinity,
                      height: 50,
                      child: ElevatedButton.icon(
                        icon: const Text('🤖', style: TextStyle(fontSize: 18)),
                        label: const Text('お題から生成・鑑定', style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
                        style: ElevatedButton.styleFrom(
                          backgroundColor: const Color(0xFF5B8124),
                          foregroundColor: Colors.white,
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                        ),
                        onPressed: _isGenerating ? null : _startGeneration,
                      ),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 32),
            if (_taskStream != null)
              StreamBuilder<NazokakeState>(
                stream: _taskStream,
                builder: (context, snapshot) {
                  if (snapshot.hasError) {
                    _isGenerating = false;
                    return Text('通信エラー: ${snapshot.error}', style: const TextStyle(color: Colors.red));
                  }
                  if (!snapshot.hasData) return const CircularProgressIndicator();
                  final state = snapshot.data!;
                  if (state.status == 'completed' && state.result != null) {
                    WidgetsBinding.instance.addPostFrameCallback((_) {
                      if (mounted && _isGenerating) setState(() => _isGenerating = false);
                    });
                    return Card(
                      elevation: 4,
                      child: Padding(
                        padding: const EdgeInsets.all(16.0),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text('お題: ${state.result!.hint}', style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
                            const SizedBox(height: 8),
                            Text('解き: ${state.result!.toku}', style: const TextStyle(fontSize: 16)),
                            const SizedBox(height: 8),
                            Text('心は: ${state.result!.kokoro}', style: const TextStyle(fontSize: 16)),
                          ],
                        ),
                      ),
                    );
                  }
                  if (state.status == 'error' || state.status == 'timeout') {
                    WidgetsBinding.instance.addPostFrameCallback((_) {
                      if (mounted && _isGenerating) setState(() => _isGenerating = false);
                    });
                    return Text('エラー: ${state.message}', style: const TextStyle(color: Colors.red));
                  }
                  return Column(
                    children: [
                      const CircularProgressIndicator(),
                      const SizedBox(height: 16),
                      Text(state.message, style: const TextStyle(fontSize: 16, color: Colors.blueGrey)),
                    ],
                  );
                },
              ),
          ],
        ),
      ),
    );
  }
}
"""
with open("lib/screens/home_screen.dart", "w", encoding="utf-8") as f:
    f.write(home_code)

# 4. AppCheckの400エラーと画面間延びを防ぐ完全版 main.dart を復元
main_code = """import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart';
import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_app_check/firebase_app_check.dart';
import 'firebase_options.dart';
import 'screens/main_tab_screen.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Firebase.initializeApp(options: DefaultFirebaseOptions.currentPlatform);
  
  // Web版ではAppCheckをスキップし、400エラーを完全に防ぐ
  if (!kIsWeb) {
    await FirebaseAppCheck.instance.activate(
      androidProvider: AndroidProvider.debug,
      appleProvider: AppleProvider.debug,
    );
  }
  
  runApp(const MyApp());
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: '謎掛け学術振興会',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        fontFamilyFallback: const ['Hiragino Sans', 'Meiryo', 'sans-serif'],
        scaffoldBackgroundColor: const Color(0xFFF9F9F9),
        colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF902A19)),
        appBarTheme: const AppBarTheme(
          backgroundColor: Color(0xFF902A19),
          foregroundColor: Colors.white,
          centerTitle: true,
          elevation: 0,
        ),
        useMaterial3: true,
      ),
      builder: (context, child) {
        return Container(
          color: Colors.grey[300],
          child: Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 450),
              child: ClipRect(child: child),
            ),
          ),
        );
      },
      home: const MainTabScreen(),
    );
  }
}
"""
with open("lib/main.dart", "w", encoding="utf-8") as f:
    f.write(main_code)

print("✅ [SUCCESS] 10:00時点のコードベース完全復元に成功しました！")

```


# ==========================================
# 📄 File: .\frontend\patch_appcheck.py
# ==========================================
```py
import re
import sys

file_path = "lib/main.dart"
try:
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 正規表現で古い FirebaseAppCheck のブロックを正確に捕捉して置換
    pattern = re.compile(r"await\s+FirebaseAppCheck\.instance\.activate\s*\([^)]+\);", re.DOTALL)
    
    new_block = """await FirebaseAppCheck.instance.activate(
    webProvider: ReCaptchaEnterpriseProvider('YOUR_RECAPTCHA_SITE_KEY'),
    androidProvider: AndroidProvider.debug,
    appleProvider: AppleProvider.debug,
  );"""

    if pattern.search(content):
        new_content = pattern.sub(new_block, content)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        print("✅ [SUCCESS] main.dart の AppCheck Web対応パッチを適用しました！")
    else:
        print("⚠️ [SKIP] 置換対象が見つかりません。既に修正されているか、形式が異なります。")

except Exception as e:
    print(f"🚨 [ERROR] パッチ適用失敗: {e}")
    sys.exit(1)

```
