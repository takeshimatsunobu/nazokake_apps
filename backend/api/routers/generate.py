"""生成ドメインルーター（Progressive Disclosure / 時間差おまけ生成）。

POST /generate        : お題を受け取り、生成を背景で発火して即座に task_id を返す（非ブロッキング）。
GET  /status/{doc_id} : 段階的ステータス（processing → gemini_completed → all_completed）をポーリングする。

フロー（生成と評価を分離）:
  1. Gemini 生成 → status:gemini_generated（本文先行）→ 評価 → status:gemini_completed
  2. 裏でローカル ELYZA 生成 → llmjp_status:generated（本文先行）→ 評価 → status:all_completed
Gemini(信頼パス)の失敗のみ status:error。ELYZA(おまけ)の失敗は graceful（llmjp_status:failed）。
"""

import asyncio
import random
from loguru import logger

from fastapi import APIRouter, Depends, HTTPException
from firebase_admin import firestore

from api.deps import get_db, serialize_doc, handle_exceptions
from api.routers.admin_costs import is_budget_exceeded
from models.schemas import GenerateRequest
from services.generation import generate_via_gemini, generate_via_llmjp
from services.evaluation import run_evaluation, AXES
from nazokake_core.schemas import Result, Scores

router = APIRouter()

# 背景タスクの参照を保持し GC を防ぐ（サイレントデス対策）
_bg_tasks: set = set()


def _compose_text(odai: str, result: dict) -> str:
    return f"「{odai}」とかけて、「{result.get('toku', '')}」と解く。\nその心は、{result.get('kokoro', '')}"


def _validate_result_with_fallback(raw: dict, fallback_message: str) -> dict:
    """Resultスキーマで検証する。壊れたデータでもアプリを落とさず、
    仮の値(エラー表示用)で補完した合法なResultを返す(自己修復)。"""
    try:
        return Result(**raw).model_dump()
    except Exception as e:
        logger.warning(f"⚠️ Resultバリデーションエラー(自己修復を試みます): {e}")
        return Result(
            hint="生成エラー", toku="エラー", kokoro=fallback_message
        ).model_dump()


def _validate_scores_with_fallback(raw: dict) -> dict:
    """Scoresスキーマ(11軸)で検証する。壊れたデータでもアプリを落とさず、
    全軸を中間値0.5で補完した合法なScoresを返す(自己修復)。"""
    try:
        return Scores(**raw).model_dump()
    except Exception as e:
        logger.warning(f"⚠️ Scoresバリデーションエラー(自己修復を試みます): {e}")
        return Scores(**{axis: 0.5 for axis in AXES}).model_dump()


async def progressive_generate(db, doc_id: str, odai: str):
    """段階的開示の本体。Gemini と ELYZA を「完全に独立した並列フロー」で実行する。

    各モデルが自分のペースで「生成 → 本文先行update → 評価 → 評価後update」を進め、
    互いの完了を一切待たない（asyncio.gather で真の並行）。これにより ELYZA 本文の表示が
    Gemini の評価完了にブロックされなくなる。最後に全体を all_completed へ更新する。
    フロー(並行): [Gemini] gemini_generated→gemini_completed / [ELYZA] llmjp:generated→llmjp:completed → all_completed。
    """
    doc_ref = db.collection("nazokake_items").document(doc_id)

    # 予算ソフトリミット判定: 超過していても外部API(Gemini等)の呼び出しは継続する。
    # ローカルLLMへの強制フォールバックは行わず、警告ログとUI向けメッセージのみ付与する。
    budget_exceeded = await is_budget_exceeded(db)
    if budget_exceeded:
        logger.warning("🚨 予算上限を超過していますが、外部APIによる生成を継続します")

    async def process_gemini() -> bool:
        """主軸パス: 生成→本文先行→評価→スコア。失敗は status:error を書き、False を返す。"""
        try:
            g = await generate_via_gemini(odai)
            validated_result = _validate_result_with_fallback(
                g, "生成結果の検証に失敗しました"
            )
            text_g = _compose_text(odai, validated_result)
            gemini_message = (
                "⚠️ 予算超過: 分析官が採点中..."
                if budget_exceeded
                else "分析官が採点中..."
            )
            await asyncio.to_thread(
                doc_ref.update,
                {
                    "result_gemini": validated_result,
                    "result": validated_result,
                    "nazokake_text": text_g,
                    "status": "gemini_generated",
                    "message": gemini_message,
                },
            )
            ev = await run_evaluation(odai, text_g)
            validated_scores = _validate_scores_with_fallback(ev["scores"])
            await asyncio.to_thread(
                doc_ref.update,
                {
                    "scores": validated_scores,
                    "s_total": ev["s_total"],
                    "axis_comments": ev["axis_comments"],
                    "overall": ev["overall"],
                    "eval_status": "completed",
                    "feed_ready": True,
                    "status": "gemini_completed",
                    "message": "Gemini鑑定完了！",
                    "evaluated_at": firestore.SERVER_TIMESTAMP,
                },
            )
            return True
        except Exception as e:
            await asyncio.to_thread(
                doc_ref.update,
                {
                    "status": "error",
                    "eval_status": "error",
                    "message": f"即時生成に失敗: {e}",
                },
            )
            return False

    async def process_elyza() -> None:
        """おまけパス: 生成→本文先行→評価→スコア。失敗は graceful に llmjp_status:failed。"""
        try:
            raw_result_l = await generate_via_llmjp(odai)
            validated_result_l = _validate_result_with_fallback(
                raw_result_l, "生成結果の検証に失敗しました"
            )
            text_l = _compose_text(odai, validated_result_l)
            await asyncio.to_thread(
                doc_ref.update,
                {
                    "result_llmjp": validated_result_l,
                    "nazokake_text_llmjp": text_l,
                    "llmjp_status": "generated",
                    "message": "ELYZA作品を採点中...",
                },
            )
            ev_l = await run_evaluation(odai, text_l)
            validated_scores_l = _validate_scores_with_fallback(ev_l["scores"])
            await asyncio.to_thread(
                doc_ref.update,
                {
                    "scores_llmjp": validated_scores_l,
                    "s_total_llmjp": ev_l["s_total"],
                    "axis_comments_llmjp": ev_l["axis_comments"],
                    "overall_llmjp": ev_l["overall"],
                    "llmjp_status": "completed",
                },
            )
        except Exception as e:
            logger.exception(f"⚠️ おまけ(ELYZA)生成/評価に失敗: {e}")
            await asyncio.to_thread(
                doc_ref.update,
                {"llmjp_status": "failed", "message": f"ELYZAお休み理由: {e}"},
            )

    # 【真の並行】Gemini と ELYZA を同時に発火し、双方の完了を待ち合わせる（各々が自前で例外処理）。
    gemini_ok, _ = await asyncio.gather(process_gemini(), process_elyza())

    # 【最終】Gemini 成功時のみ全体完了へ。失敗時は status:error を保持し無限ロードを防ぐ。
    if gemini_ok:
        await asyncio.to_thread(
            doc_ref.update, {"status": "all_completed", "message": "完成！"}
        )


async def _guarded_progressive(db, doc_id: str, odai: str):
    """未捕捉例外でもDBに必ず error を書き、無限ロード（サイレントデス）を防ぐ最終防壁。"""
    try:
        await progressive_generate(db, doc_id, odai)
    except Exception as e:
        logger.exception(f"[{doc_id}] 背景タスク(生成・評価)で致命的エラー発生: {e}")
        try:
            await asyncio.to_thread(
                db.collection("nazokake_items").document(doc_id).update,
                {"status": "error", "eval_status": "error", "message": str(e)},
            )
        except Exception as db_e:
            logger.error(f"[{doc_id}] エラーステータスのDB書き込みに失敗: {db_e}")


@router.get("/status/{doc_id}")
@handle_exceptions
def get_status(doc_id: str, db=Depends(get_db)):
    doc = db.collection("nazokake_items").document(doc_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Not found")
    data = serialize_doc(doc)
    return {
        "status": data.get("status", "unknown"),
        "eval_status": data.get("eval_status", "unknown"),
        "llmjp_status": data.get("llmjp_status", "none"),
        "message": data.get("message", ""),
        "odai": data.get("odai", ""),
        # 主（Gemini）結果＋評価（既存UI互換: result/scores/overall/axis_comments/s_total）
        "result": data.get("result", {}),
        "result_gemini": data.get("result_gemini", {}),
        "scores": data.get("scores", {}),
        "reasoning": data.get("reasoning", ""),
        "overall": data.get("overall", ""),
        "axis_comments": data.get("axis_comments", {}),
        "s_total": data.get("s_total", 0.0),
        # おまけ（ELYZA）結果＋評価
        "result_llmjp": data.get("result_llmjp", {}),
        "scores_llmjp": data.get("scores_llmjp", {}),
        "overall_llmjp": data.get("overall_llmjp", ""),
        "axis_comments_llmjp": data.get("axis_comments_llmjp", {}),
        "s_total_llmjp": data.get("s_total_llmjp", 0.0),
    }


@router.post("/generate")
@handle_exceptions
async def generate_ai(req: GenerateRequest, db=Depends(get_db)):
    doc_ref = db.collection("nazokake_items").document()
    await asyncio.to_thread(
        doc_ref.set,
        {
            "odai": req.odai,
            "status": "processing",
            "eval_status": "processing",
            "llmjp_status": "pending",
            "message": "AIが生成中...",
            "timestamp": firestore.SERVER_TIMESTAMP,
            "random_weight": random.random(),
        },
    )
    # 背景で生成パイプラインを発火し、即座にレスポンスを返す（HTTPをブロックしない）
    task = asyncio.create_task(_guarded_progressive(db, doc_ref.id, req.odai))
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return {"status": "processing", "task_id": doc_ref.id}
