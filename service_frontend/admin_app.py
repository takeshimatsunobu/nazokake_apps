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
