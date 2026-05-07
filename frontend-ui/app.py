import streamlit as st
import plotly.graph_objects as go
from db_client import fetch_evaluated_data, save_human_evaluation
from ranking_calc import EVAL_AXES, get_preset_weights, calculate_dynamic_score

st.set_page_config(page_title="なぞかけ評価ダッシュボード", layout="wide", page_icon="🎭")

if "weights" not in st.session_state:
    st.session_state.weights = {axis[2]: 1.0 for axis in EVAL_AXES}

# 1. データのフェッチ
raw_df = fetch_evaluated_data()

# 2. サイドバー (UI)
with st.sidebar:
    st.header("⚙️ 評価ウェイト調整")
    presets = get_preset_weights()
    selected_preset = st.selectbox("🎯 プリセット", list(presets.keys()))
    
    if st.button("適用する", use_container_width=True):
        st.session_state.weights = presets[selected_preset].copy()
        st.rerun()

    st.markdown("---")
    for axis_col, axis_label, weight_key in EVAL_AXES:
        st.session_state.weights[weight_key] = st.slider(
            f"{axis_label} ({axis_col})", 0.0, 3.0, float(st.session_state.weights[weight_key]), 0.1
        )

# 3. 計算
df = calculate_dynamic_score(raw_df, st.session_state.weights)

st.title("🎭 なぞかけ自動評価ダッシュボード")

if df.empty:
    st.info("評価完了データがありません。Firestoreにstatus=2のデータが存在するか確認してください。")
    st.stop()

# 4. メイン画面 (テーブル)
col1, col2 = st.columns([1, 1])
with col1:
    show_borderline = st.checkbox("🔍 境界線データ（S_total: 0.4〜0.6）のみ表示")
with col2:
    hide_evaluated = st.checkbox("✅ RLHF評価済みのデータを隠す", value=True)

display_df = df.copy()
if show_borderline:
    display_df = display_df[(display_df["S_total"] >= 0.4) & (display_df["S_total"] <= 0.6)]
if hide_evaluated and "FINAL_SCORE_HUMAN" in display_df.columns:
    display_df = display_df[display_df["FINAL_SCORE_HUMAN"].isna()]

st.subheader("🏆 暫定ランキング")
st.dataframe(
    display_df[["S_total", "S_nat", "nazokake_text", "A_TITLE", "B_TITLE"]].style.format({"S_total": "{:.3f}", "S_nat": "{:.2f}"}),
    use_container_width=True, height=250, 
    selection_mode="single-row", on_select="rerun", key="ranking_table"
)

st.markdown("---")

# 5. 詳細分析 & レーダーチャート
st.subheader("📊 詳細分析 & RLHFフィードバック")

# テーブルで選択された行を取得
selected_rows = st.session_state.ranking_table.selection.rows

if selected_rows:
    target = display_df.iloc[selected_rows[0]]
    c_info, c_chart = st.columns([1, 1])
    
    with c_info:
        st.info(f"**【なぞかけ本文】**\n\n{target.get('nazokake_text', '')}")
        st.write(f"**AI推論根拠 (reasoning):**\n{target.get('reasoning', '記録なし')}")
        st.metric(label="暫定総合スコア", value=f"{target.get('S_total', 0):.3f}", delta=f"ペナルティ乗数(S_nat): {target.get('S_nat', 1.0):.2f}", delta_color="off")
        
        st.markdown("##### 人間の評価 (RLHF)")
        btn1, btn2 = st.columns(2)
        if btn1.button("👍 いいね (1.0)", use_container_width=True, type="primary"):
            save_human_evaluation(target["id"], 1.0)
            st.success("「いいね」を記録しました！再読み込みしてください。")
        if btn2.button("👎 いまいち (0.0)", use_container_width=True):
            save_human_evaluation(target["id"], 0.0)
            st.warning("「いまいち」を記録しました。")

    with c_chart:
        categories = [label for _, label, _ in EVAL_AXES]
        values = [target.get(col, 0.0) for col, _, _ in EVAL_AXES]
        categories.append(categories[0])
        values.append(values[0])
        
        fig = go.Figure()
        fig.add_trace(go.Scatterpolar(r=values, theta=categories, fill='toself', line_color='#1f77b4', fillcolor='rgba(31, 119, 180, 0.4)'))
        fig.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0, 1])), showlegend=False, margin=dict(t=20, b=20, l=40, r=40))
        st.plotly_chart(fig, use_container_width=True)
else:
    st.info("👆 上のテーブルからなぞかけの行をクリックして選択すると、ここに詳細とグラフが表示されます。")