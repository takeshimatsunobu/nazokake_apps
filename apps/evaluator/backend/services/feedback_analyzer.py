"""
feedback_analyzer.py
=====================
Phase 4 Lv.2: AIの自己評価(scores)とユーザーのaxis_feedback(good/bad)を突き合わせ、
「AIが過信している軸」を検出する乖離分析ロジック。

注意(スケールの換算): nazokake_core.schemas.Scores の各軸は 0.0〜1.0 の小数で
保存されている(5点満点の整数ではない)。本モジュールでの「高スコア」判定は
AI_HIGH_SCORE_THRESHOLD(既定0.8 = 5点満点中4点相当)を基準に行う。

model_target(gemini/elyza)により、AIスコアの参照先フィールドを切り替える
(gemini→scores, elyza→scores_llmjp)。異なるモデルの出力に対するフィードバックを
別モデルのスコアと突き合わせないようにするための対応。
"""

import asyncio
from typing import Optional

from firebase_admin import firestore

from nazokake_core.database import async_get_item

# 0.0〜1.0スケールでの「高評価」の閾値。5点満点中4点以上に相当(4/5 = 0.8)。
AI_HIGH_SCORE_THRESHOLD = 0.8

_SCORES_FIELD_BY_MODEL_TARGET = {
    "gemini": "scores",
    "elyza": "scores_llmjp",
}


def _fetch_recent_feedbacks_sync(db, limit: int) -> list:
    """Firestoreのstream()を同期的に実行し、リスト化して返すヘルパー関数"""
    query = (
        db.collection("user_feedbacks")
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .limit(limit)
    )
    return [doc.to_dict() for doc in query.stream()]


async def _fetch_ai_scores(doc_id: str, model_target: str) -> Optional[dict]:
    """指定doc_idのnazokake_items(ローカルDB)から、model_targetに対応するAIの
    11軸スコアを取得する。"""
    data = await async_get_item(doc_id)
    if data is None:
        return None
    field = _SCORES_FIELD_BY_MODEL_TARGET.get(model_target, "scores")
    scores = data.get(field)
    return scores if isinstance(scores, dict) else None


async def analyze_axis_divergence(db, limit: int = 100) -> dict:
    """AIの自己評価とユーザー評価の乖離(過信)を軸ごとに集計する。

    「AIのスコアがAI_HIGH_SCORE_THRESHOLD以上、かつユーザー評価がbad」であるケースを
    過信(overconfident)としてカウントする。axis_feedbackが空のフィードバックや、
    対応するnazokake_itemsが存在しない/スコア欠損のケースはスキップする。

    返り値:
        {
            "total_feedback_analyzed": int,   # 実際に突き合わせ集計できたフィードバック件数
            "axes": {
                "<axis_name>": {
                    "bad_count": int,             # そのAxisにbadが付いた回数
                    "high_score_count": int,      # AIがそのAxisを閾値以上と評価した回数
                    "overconfident_count": int,   # 上記2条件が重なった(AI高評価&ユーザーbad)回数
                    "overconfidence_rate": float, # overconfident_count / high_score_count(0除算は0.0)
                },
                ...
            },
        }
    """
    feedbacks = await asyncio.to_thread(_fetch_recent_feedbacks_sync, db, limit)

    axes_bad_count: dict = {}
    axes_high_score_count: dict = {}
    axes_overconfident_count: dict = {}

    analyzed = 0
    for fb in feedbacks:
        axis_feedback = fb.get("axis_feedback") or {}
        if not axis_feedback:
            continue
        doc_id = fb.get("doc_id")
        if not doc_id:
            continue
        model_target = fb.get("model_target", "gemini")

        ai_scores = await _fetch_ai_scores(doc_id, model_target)
        if ai_scores is None:
            continue

        analyzed += 1
        for axis, verdict in axis_feedback.items():
            ai_score = ai_scores.get(axis)
            if ai_score is None:
                continue
            is_high = ai_score >= AI_HIGH_SCORE_THRESHOLD
            if is_high:
                axes_high_score_count[axis] = axes_high_score_count.get(axis, 0) + 1
            if verdict == "bad":
                axes_bad_count[axis] = axes_bad_count.get(axis, 0) + 1
                if is_high:
                    axes_overconfident_count[axis] = (
                        axes_overconfident_count.get(axis, 0) + 1
                    )

    axes_result = {}
    for axis in set(axes_bad_count) | set(axes_high_score_count):
        high_count = axes_high_score_count.get(axis, 0)
        overconfident = axes_overconfident_count.get(axis, 0)
        axes_result[axis] = {
            "bad_count": axes_bad_count.get(axis, 0),
            "high_score_count": high_count,
            "overconfident_count": overconfident,
            "overconfidence_rate": round(overconfident / high_count, 4)
            if high_count
            else 0.0,
        }

    return {"total_feedback_analyzed": analyzed, "axes": axes_result}


def generate_correction_prompt(analysis_data: dict, rate_threshold: float = 0.5) -> str:
    """analyze_axis_divergence() の結果から、過信軸への自己評価補正を促す自然言語プロンプトを生成する。

    overconfidence_rate が rate_threshold 以上の軸を抽出し、評価プロンプトに追記できる
    警告文を組み立てる。対象軸が無ければ空文字を返す(= 補正不要、既存挙動を変えない)。
    """
    axes = analysis_data.get("axes", {})
    flagged = sorted(
        axis
        for axis, stats in axes.items()
        if stats.get("overconfidence_rate", 0.0) >= rate_threshold
    )
    if not flagged:
        return ""
    return (
        "【自己評価の補正指示】以下の軸は過去に過大評価の傾向が指摘されています。"
        f"通常より厳格に判定してください: {', '.join(flagged)}"
    )
