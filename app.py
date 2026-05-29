import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.base_query import FieldFilter
import json
import re
import pandas as pd
import plotly.express as px
from utils.llm_router import DualAIRouter

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

tabs = ["💡 AI生成", "✍️ 自作鑑定", "🌱 評価して育てる", "👑 殿堂入り"]
selected_tab = st.sidebar.radio("ナビゲーション", tabs)

if selected_tab == "💡 AI生成":
    st.subheader("Tier 1 (Gemma-2-9B) による高速なぞかけ創出")
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
                
                # 🛑 クラウド側の本物スキーマに合わせて保存（A_TITLE, nazokake_text, status: 0）
                try:
                    db.collection('nazokake_items').document().set({
                        "A_TITLE": topic,
                        "nazokake_text": ai_text,
                        "generator": "gemma-2-9b-it",
                        "created_at": firestore.SERVER_TIMESTAMP,
                        "status": 0  # 0: 未処理・評価待ち
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
        
        with st.spinner("🔍 [Tier 1] 辞書エージェントが日本の文化背景・隠れた文脈を解析中..."):
            ctx_result = router.generate_chat("あなたは文化背景抽出エージェントです。事実と文脈だけを簡潔に出力してください。", f"お題「{odai}」、掛け「{kake}」、解き「{toku}」、こころ「{kokoro}」の文化的背景を解説してください。", tier=1)
            if ctx_result["error"]: st.stop()
            context_text = ctx_result["text"]

        with st.spinner("⚖️ [Tier 2] 最高峰のAI審査員が採点中..."):
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
    
    # 🛑 クラウド側の本物スキーマに合わせて取得（status == 0 または status == None）
    try:
        docs = db.collection('nazokake_items').where(filter=FieldFilter('status', '==', 0)).limit(1).stream()
        target_item = None
        for doc in docs:
            target_item = doc.to_dict()
            target_item['id'] = doc.id
            
        if not target_item:
            st.info("🎉 現在評価待ち(status:0)のデータはありません！「💡 AI生成」タブで新しく作らせてください。")
        else:
            odai_text = target_item.get('A_TITLE', target_item.get('odai', '不明'))
            nazo_text = target_item.get('nazokake_text', target_item.get('text', ''))
            
            st.markdown(f"<div class='rlhf-box'><h4>お題：{odai_text}</h4><p style='font-size:1.2em;'>{nazo_text}</p></div>", unsafe_allow_html=True)
            
            with st.form("rlhf_form"):
                st.markdown("### 👨‍🏫 名匠の採点と添削")
                human_score = st.slider("このAIの作品は何点？ (1: 駄作 〜 5: 傑作)", 1, 5, 3)
                human_correction = st.text_area("人間の模範解答 / 添削", placeholder="〇〇とかけて、××ととく。そのこころは、□□（同音異義語）でしょう。")
                
                if st.form_submit_button("💾 評価を記録してAIの血肉にする"):
                    db.collection('nazokake_evaluations').add({
                        "original_item_id": target_item['id'],
                        "A_TITLE": odai_text,
                        "nazokake_text": nazo_text,
                        "human_score": human_score,
                        "human_correction": human_correction,
                        "created_at": firestore.SERVER_TIMESTAMP
                    })
                    # クラウド側の本物スキーマに合わせて更新（status: 2 = 処理完了）
                    db.collection('nazokake_items').document(target_item['id']).update({"status": 2})
                    st.success("✅ 評価を記録しました！画面をリロードすると次の作品が表示されます。")
    except Exception as e:
        st.error(f"🚨 データの取得中にエラーが発生しました: {e}")

elif selected_tab == "👑 殿堂入り":
    st.subheader("👑 殿堂入り (順次復旧予定)")
    st.info("旧UIのデータベース連携部分をここにマージしていきます。")

