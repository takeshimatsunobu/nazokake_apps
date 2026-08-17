"""生成ドメインルーター（Progressive Disclosure / 時間差おまけ生成）。

POST /generate        : お題を受け取り、生成を背景で発火して即座に task_id を返す（非ブロッキング）。
GET  /status/{doc_id} : 段階的ステータス（processing → gemini_completed → all_completed）をポーリングする。

フロー（生成と評価を分離）:
  1. Gemini 生成 → status:gemini_generated（本文先行）→ 評価 → status:gemini_completed
  2. 裏でELYZA 生成 → llmjp_status:generated（本文先行）→ 評価 → status:all_completed
     【Push型アーキテクチャ(2026-08-18)】Firestoreジョブキュー(elyza_job_status
     経由のポーリング・8秒ACK待ち・ワーカー監視、instructions/250)を廃止し、
     Cloud RunからCloudflare Tunnel経由で自宅PCのOllamaへ直接HTTP POSTする
     方式(services/generation.py::generate_via_elyza_direct、環境変数
     LOCAL_ELYZA_ENDPOINT)へ統一した。接続確立3秒/推論15秒という短い
     タイムアウトで即座に諦め、Firestoreの往復を挟まずGemini Flash Lite
     代打へ切り替える(process_elyza参照)。ローカル開発機でLOCAL_ELYZA_ENDPOINT
     未設定・K_SERVICE未設定の場合のみ、従来通りlocalhost直叩き
     (generate_via_llmjp)を試みる。
Gemini(信頼パス)の失敗のみ status:error。ELYZA(おまけ)の失敗は graceful（llmjp_status:failed）。

【Local-First】永続化先はFirestoreではなく packages/shared_core/nazokake_core/database.py の
Serialized Writer(ローカルSQLite)。async_upsert_item() は内部で1回のopen→commit→closeが
完結する単発呼び出しであり、LLM推論(generate_via_gemini/generate_via_llmjp/run_evaluation、
数秒〜数十秒)を待機している間にDB接続やトランザクションを保持し続けることは一切ない。
"""

import asyncio
import os
import random
import uuid
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from fastapi import APIRouter, Depends, HTTPException
from firebase_admin import firestore

from api.deps import get_db, handle_exceptions
from api.routers.admin_costs import is_budget_exceeded
from api.routers.persona_generate import _resolve_persona_for_generation
from models.schemas import GenerateRequest
from nazokake_core import narrator_personas
from services.generation import (
    ElyzaDirectUnavailable,
    generate_via_elyza_direct,
    generate_via_gemini,
    generate_via_llmjp,
)
from services.evaluation import run_evaluation, AXES
from services.step2_generation import _compose_persona_prompt
from nazokake_core.database import async_get_item, async_upsert_item
from nazokake_core.firestore_sync import (
    _ensure_firebase_app,
    _normalize_for_sqlite,
    _resolve_collection,
    sync_once_safe,
)
from nazokake_core.quality_circuit_breaker import async_record_evaluation_score
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


async def progressive_generate(
    db,
    doc_id: str,
    odai: str,
    pair_id: str,
    persona_prompt: str | None = None,
    temperature: float | None = None,
    narrator_persona_id: str | None = None,
):
    """段階的開示の本体。Gemini と ELYZA を「完全に独立した並列フロー」で実行する。

    各モデルが自分のペースで「生成 → 本文先行update → 評価 → 評価後update」を進め、
    互いの完了を一切待たない（asyncio.gather で真の並行）。これにより ELYZA 本文の表示が
    Gemini の評価完了にブロックされなくなる。最後に全体を all_completed へ更新する。
    フロー(並行): [Gemini] gemini_generated→gemini_completed / [ELYZA] llmjp:generated→llmjp:completed → all_completed。

    pair_id: バッチ工場(batch/main.py)と同一フォーマットの dpo_pair_id。Gemini/ELYZA
    両パスのローカルDB更新に記録し、抽出スクリプトがバッチ由来・アプリ由来を同一ロジックで
    ペア回収できるようにする。

    各 async_upsert_item() 呼び出しは独立した単発のDB往復であり、その前後にある
    generate_via_gemini/generate_via_llmjp/run_evaluation(LLM推論)の実行中はDBに
    一切触れない。
    """
    # 予算ソフトリミット判定: 超過していても外部API(Gemini等)の呼び出しは継続する。
    # ローカルLLMへの強制フォールバックは行わず、警告ログとUI向けメッセージのみ付与する。
    budget_exceeded = await is_budget_exceeded(db)
    if budget_exceeded:
        logger.warning("🚨 予算上限を超過していますが、外部APIによる生成を継続します")

    async def process_gemini() -> bool:
        """主軸パス: 生成→本文先行→評価→スコア。失敗は status:error を書き、False を返す。"""
        try:
            g = await generate_via_gemini(odai, persona_prompt, temperature)
            validated_result = _validate_result_with_fallback(
                g, "生成結果の検証に失敗しました"
            )
            text_g = _compose_text(odai, validated_result)
            gemini_message = (
                "⚠️ 予算超過: 分析官が採点中..."
                if budget_exceeded
                else "分析官が採点中..."
            )
            await async_upsert_item(
                {
                    "doc_id": doc_id,
                    "result_gemini": validated_result,
                    "result": validated_result,
                    "nazokake_text": text_g,
                    "status": "gemini_generated",
                    "message": gemini_message,
                    "dpo_pair_id": pair_id,
                }
            )
            ev = await run_evaluation(odai, text_g)
            # 【instructions/182: 品質のサーキットブレーカー】評価スコアがN回連続で
            # 極端値(スケール最高/最低)に偏っている場合、QualityCircuitBreakerErrorが
            # 送出される。このリクエスト単位のtry/exceptがそのまま吸収し、他の並行
            # リクエストやサーバープロセス自体には影響しない(常駐サーバーのため、
            # apps/batch_factoryのような自律ループのプロセス強制終了はここでは行わない)。
            # 【persona_feature_plan_v3.md Phase5 §5.4】pipeline_idの末尾に
            # narrator_persona_idを付与し、ペルソナごとに品質監視ウィンドウを
            # 分離する(1ペルソナの不調が他ペルソナの健全なカウンタを汚さないため)。
            await async_record_evaluation_score(
                f"live_evaluation_gemini::{narrator_persona_id}", ev["s_total"]
            )
            validated_scores = _validate_scores_with_fallback(ev["scores"])
            await async_upsert_item(
                {
                    "doc_id": doc_id,
                    "scores": validated_scores,
                    "s_total": ev["s_total"],
                    "axis_comments": ev["axis_comments"],
                    "overall": ev["overall"],
                    "eval_status": "completed",
                    "feed_ready": True,
                    "status": "gemini_completed",
                    "message": "Gemini鑑定完了！",
                    "evaluated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            return True
        except Exception as e:
            logger.exception(f"[{doc_id}] Geminiパスで致命的エラー発生: {e}")
            await async_upsert_item(
                {
                    "doc_id": doc_id,
                    "status": "error",
                    "eval_status": "error",
                    "message": "システム内部で予期せぬエラーが発生しました",
                }
            )
            return False

    async def process_elyza_pinch_hitter(reason: str) -> None:
        """【緊急対応】自宅ELYZAワーカーの通信回線不調により、Cloud Run本番でも
        オンデマンドジョブキュー(経路B、workers/ondemand_elyza_worker.py)を
        待たず、その場でGemini Flash Liteに代打生成させる。

        ELYZA枠(llmjp_*)のフィールド形状はそのまま流用しつつ、実際に生成した
        モデルをllmjp_model_id/llmjp_is_pinch_hitterへ正確に記録する(「ELYZA」
        という虚偽のデータをどのカラムにも書き込まない)。ペルソナ・温度は
        本来ELYZAが使う予定だったものをそのまま引き継ぐ。

        reason: 代打が発火した理由の機械可読な識別子(llmjp_fallback_reasonへ
        記録し、GET /status/{doc_id}のfallback_reasonとして公開する)。
        呼び出し元(process_elyza)が"worker_ack_timeout"
        (8秒ACKタイムアウト)/"worker_completion_timeout"(ACK後の完了待機
        タイムアウト)/"worker_dead_letter"(ワーカー自身の恒久失敗確定)を渡す。
        """
        pinch_hitter_model_id = "gemini-3.5-flash-lite"
        try:
            raw_result_l = await generate_via_gemini(
                odai, persona_prompt, temperature, model_id=pinch_hitter_model_id
            )
            validated_result_l = _validate_result_with_fallback(
                raw_result_l, "生成結果の検証に失敗しました"
            )
            text_l = _compose_text(odai, validated_result_l)
            # 【ディープ監査#1】"message"は process_gemini() が単独所有するフィールド
            # として扱う(process_gemini/process_elyzaがasyncio.gatherで真に並行
            # 実行されるため、共有すると書き込み順序次第でどちらのメッセージが
            # 最終的に残るか不定になるレースがあった)。ELYZA/代打経路の進捗は
            # llmjp_status/llmjp_is_pinch_hitter等の専用フィールドで表現済みのため、
            # ここでは"message"を書かない。
            await async_upsert_item(
                {
                    "doc_id": doc_id,
                    "result_llmjp": validated_result_l,
                    "nazokake_text_llmjp": text_l,
                    "llmjp_status": "generated",
                    "llmjp_model_id": pinch_hitter_model_id,
                    "llmjp_is_pinch_hitter": True,
                    "llmjp_fallback_reason": reason,
                    "dpo_pair_id": pair_id,
                }
            )
            ev_l = await run_evaluation(odai, text_l)
            # 【persona_feature_plan_v3.md Phase5 §5.4】pipeline_idの末尾に
            # narrator_persona_idを付与し、ペルソナごとに品質監視ウィンドウを分離する。
            await async_record_evaluation_score(
                f"live_evaluation_elyza::{narrator_persona_id}", ev_l["s_total"]
            )
            validated_scores_l = _validate_scores_with_fallback(ev_l["scores"])
            await async_upsert_item(
                {
                    "doc_id": doc_id,
                    "scores_llmjp": validated_scores_l,
                    "s_total_llmjp": ev_l["s_total"],
                    "axis_comments_llmjp": ev_l["axis_comments"],
                    "overall_llmjp": ev_l["overall"],
                    "llmjp_status": "completed",
                }
            )
        except Exception as e:
            logger.exception(f"[{doc_id}] Gemini代打パスで致命的エラー発生: {e}")
            await async_upsert_item(
                {
                    "doc_id": doc_id,
                    "llmjp_status": "failed",
                    "llmjp_model_id": pinch_hitter_model_id,
                    "llmjp_is_pinch_hitter": True,
                    "llmjp_fallback_reason": reason,
                }
            )

    async def process_elyza() -> None:
        """おまけパス: 生成→本文先行→評価→スコア。失敗は graceful に llmjp_status:failed。

        【Push型アーキテクチャ(2026-08-18)】Firestoreジョブキュー(elyza_job_status
        経由のACKポーリング・ワーカー監視)を廃止した。LOCAL_ELYZA_ENDPOINTが
        設定されていれば、環境(Cloud Run/ローカル開発)を問わずCloudflare Tunnel
        経由で自宅PCのOllamaへ直接POSTする(generate_via_elyza_direct、接続確立
        3秒/推論15秒でタイムアウト)。未設定の場合は、K_SERVICE未設定(ローカル
        開発機で自宅PC自身がバックエンドも動かしている想定)に限り、従来通り
        localhost直叩き(generate_via_llmjp)を試みる。Cloud Run上でLOCAL_ELYZA_
        ENDPOINTも未設定の場合は、待たずに即座にGemini Flash Lite代打へ切り替える。

        自宅PC未起動・トンネル切断・推論遅延はいずれもElyzaDirectUnavailableへ
        正規化され、Firestoreの往復やポーリング待ちを一切挟まず即座に代打へ
        切り替わる(process_elyza_pinch_hitter)。実機から応答はあったが出力
        スキーマが不正だった場合は区別し、実際のELYZA失敗(llmjp_status:failed)
        として記録する(データ完全性のため代打への黙った差し替えは行わない、
        generate_via_llmjp()と同じ既存方針)。
        """
        if os.environ.get("LOCAL_ELYZA_ENDPOINT"):
            elyza_caller = generate_via_elyza_direct
        elif not os.getenv("K_SERVICE"):
            elyza_caller = generate_via_llmjp
        else:
            logger.warning(
                f"[{doc_id}] ⚠️ LOCAL_ELYZA_ENDPOINT未設定のCloud Run環境のため、"
                "Gemini Flash代打へ即座に切り替えます。"
            )
            await process_elyza_pinch_hitter("elyza_endpoint_not_configured")
            return

        try:
            raw_result_l = await elyza_caller(odai, persona_prompt, temperature)
            validated_result_l = _validate_result_with_fallback(
                raw_result_l, "生成結果の検証に失敗しました"
            )
            text_l = _compose_text(odai, validated_result_l)
            # 【ディープ監査#1】"message"はprocess_gemini()専有(上記pinch_hitter側と
            # 同じ理由)。
            await async_upsert_item(
                {
                    "doc_id": doc_id,
                    "result_llmjp": validated_result_l,
                    "nazokake_text_llmjp": text_l,
                    "llmjp_status": "generated",
                    "dpo_pair_id": pair_id,
                }
            )
            ev_l = await run_evaluation(odai, text_l)
            # 【instructions/182】Gemini側(live_evaluation_gemini)とは別のpipeline_idで
            # 追跡する(ELYZA/おまけ側の不調がGemini側の健全なカウンタを汚さないため)。
            # 【persona_feature_plan_v3.md Phase5 §5.4】pipeline_idの末尾に
            # narrator_persona_idを付与し、ペルソナごとに品質監視ウィンドウを分離する。
            await async_record_evaluation_score(
                f"live_evaluation_elyza::{narrator_persona_id}", ev_l["s_total"]
            )
            validated_scores_l = _validate_scores_with_fallback(ev_l["scores"])
            await async_upsert_item(
                {
                    "doc_id": doc_id,
                    "scores_llmjp": validated_scores_l,
                    "s_total_llmjp": ev_l["s_total"],
                    "axis_comments_llmjp": ev_l["axis_comments"],
                    "overall_llmjp": ev_l["overall"],
                    "llmjp_status": "completed",
                }
            )
        except ElyzaDirectUnavailable as e:
            logger.warning(
                f"[{doc_id}] ⚠️ 自宅PCへの直叩きが利用できないため({e})、"
                "Gemini Flash代打へ即座に切り替えます。"
            )
            await process_elyza_pinch_hitter(e.reason)
        except Exception as e:
            logger.exception(f"[{doc_id}] ELYZAパスで致命的エラー発生: {e}")
            await async_upsert_item(
                {
                    "doc_id": doc_id,
                    "llmjp_status": "failed",
                }
            )

    # 【真の並行】Gemini と ELYZA を同時に発火し、双方の完了を待ち合わせる（各々が自前で例外処理）。
    gemini_ok, _ = await asyncio.gather(process_gemini(), process_elyza())

    # 【最終】Gemini 成功時のみ全体完了へ。失敗時は status:error を保持し無限ロードを防ぐ。
    if gemini_ok:
        await async_upsert_item(
            {"doc_id": doc_id, "status": "all_completed", "message": "完成！"}
        )


async def _guarded_progressive(
    db,
    doc_id: str,
    odai: str,
    pair_id: str,
    persona_prompt: str | None = None,
    temperature: float | None = None,
    narrator_persona_id: str | None = None,
):
    """未捕捉例外でもDBに必ず error を書き、無限ロード（サイレントデス）を防ぐ最終防壁。"""
    try:
        await progressive_generate(
            db, doc_id, odai, pair_id, persona_prompt, temperature, narrator_persona_id
        )
    except Exception as e:
        logger.exception(f"[{doc_id}] 背景タスク(生成・評価)で致命的エラー発生: {e}")
        try:
            await async_upsert_item(
                {
                    "doc_id": doc_id,
                    "status": "error",
                    "eval_status": "error",
                    "message": "システム内部で予期せぬエラーが発生しました",
                }
            )
        except Exception as db_e:
            logger.error(f"[{doc_id}] エラーステータスのDB書き込みに失敗: {db_e}")


def _fetch_full_document_sync(doc_id: str) -> dict[str, Any] | None:
    """Firestoreの該当ドキュメントを全フィールド取得する(読み取り専用)。

    【instructions/285】Cloud Runはマルチインスタンスで稼働し得るため、
    POST /generateを処理したインスタンスと、後続のGET /status/{doc_id}を
    ルーティングされるインスタンスが異なる場合がある。各インスタンスの
    ローカルSQLite(/tmp)はインスタンス間で共有されないエフェメラルストレージの
    ため、このインスタンスのローカルにdoc_idが存在しなくても、既に他インスタンスが
    Firestoreへバックアップ済みであれば復元できる可能性がある(_fetch_completed_
    elyza_job_syncと異なり、こちらは狭いフィールド集合ではなく全件を対象とする)。
    """
    _ensure_firebase_app()
    db = firestore.client()
    snapshot = db.collection(_resolve_collection()).document(doc_id).get()
    if not snapshot.exists:
        return None
    data = snapshot.to_dict() or {}
    data["doc_id"] = doc_id
    return {k: _normalize_for_sqlite(v) for k, v in data.items()}


async def _fetch_full_document(doc_id: str) -> dict[str, Any] | None:
    """_fetch_completed_elyza_jobと同じ方針: Firestore参照失敗は吸収してNoneを返す
    (呼び出し元は「復元できなかった」として通常の404フローへフォールバックする)。
    """
    try:
        return await asyncio.to_thread(_fetch_full_document_sync, doc_id)
    except Exception as e:
        logger.warning(f"⚠️ [Status Pull] Firestoreからの全件取得に失敗: {e}")
        return None


@router.get("/status/{doc_id}")
@handle_exceptions
async def get_status(doc_id: str):
    # instructions/239: progressive_generate()自体はasyncio.create_taskで発火される
    # 検出不能なバックグラウンドタスク(FastAPIのリクエストコンテキストを持たない)ため、
    # "all_completed"等の後続状態のFirestoreバックアップは、フロントが完了まで繰り返す
    # このポーリング呼び出しに便乗させて拾う。
    # 【instructions/283】Cloud RunはCPUをリクエスト処理中のみ割り当てる仕様のため、
    # レスポンス送出後に実行されるBackgroundTasksはスケジュールされる保証が無く、
    # 同期が発火しないまま次のリクエストまでインスタンスがサスペンドされ得た
    # (instructions/282のFirestore同期欠落調査で判明)。レスポンスを返す前に
    # 同期的に完了させることで、CPUが確実に割り当てられているリクエスト処理中に
    # 同期を完結させる。
    await sync_once_safe()
    data = await async_get_item(doc_id)

    if data is None:
        # 【instructions/285】Cloud Runはマルチインスタンスで稼働し得るため、
        # POST /generateを処理したインスタンスと異なるインスタンスへこの
        # ポーリングがルーティングされた場合、このインスタンスのローカルSQLite
        # (インスタンス間で共有されないエフェメラルストレージ)にはdoc_idが
        # 存在しない。即座に404とはせず、まずFirestoreへフォールバックし、
        # 存在すればローカルSQLiteへ取り込んで(能動的Pull)処理を継続する。
        # Firestoreにも存在しない場合のみ、本当に404とする。
        remote_full = await _fetch_full_document(doc_id)
        if remote_full is not None:
            try:
                await async_upsert_item(remote_full)
                data = await async_get_item(doc_id)
            except Exception as e:
                logger.warning(
                    f"⚠️ [Status Pull] Firestoreから復元したドキュメントのローカル"
                    f"SQLiteへの保存に失敗(doc_id={doc_id}): {e}"
                )
                data = None
        if data is None:
            raise HTTPException(status_code=404, detail="Not found")

    # 【Push型アーキテクチャ(2026-08-18)】ELYZA(実機またはGemini代打)は
    # progressive_generate()内のasyncio.gatherでGeminiと同じ背景タスク内で
    # 完結するため、Firestoreジョブキューを介した非同期な後発完了を待って
    # 追いPullする仕組み(旧elyza_job_status経由)は不要になった。ローカル
    # SQLiteの値をそのまま返す。

    return {
        "status": data.get("status") or "unknown",
        "eval_status": data.get("eval_status") or "unknown",
        "llmjp_status": data.get("llmjp_status") or "none",
        # 【instructions/286】フロントエンドのポーリング終了判定用。オンデマンド
        # ジョブキュー(instructions/250)を経由しないドキュメント(ローカル直接生成
        # パスや旧データ)ではキー自体が存在せず None(=JSON null)になり得る。
        "elyza_job_status": data.get("elyza_job_status"),
        "message": data.get("message") or "",
        "odai": data.get("odai") or "",
        # 主（Gemini）結果＋評価（既存UI互換: result/scores/overall/axis_comments/s_total）
        "result": data.get("result") or {},
        "result_gemini": data.get("result_gemini") or {},
        "scores": data.get("scores") or {},
        "reasoning": data.get("reasoning") or "",
        "overall": data.get("overall") or "",
        "axis_comments": data.get("axis_comments") or {},
        "s_total": data.get("s_total") or 0.0,
        # おまけ（ELYZA）結果＋評価
        "result_llmjp": data.get("result_llmjp") or {},
        "scores_llmjp": data.get("scores_llmjp") or {},
        "overall_llmjp": data.get("overall_llmjp") or "",
        "axis_comments_llmjp": data.get("axis_comments_llmjp") or {},
        "s_total_llmjp": data.get("s_total_llmjp") or 0.0,
        # 【緊急対応: Gemini Flash Lite代打モード】フロントエンド(result.js)が
        # 「純国産AI ELYZA」表記を代打表記へ切り替えるための判定に使う。
        "llmjp_model_id": data.get("llmjp_model_id"),
        "llmjp_is_pinch_hitter": bool(data.get("llmjp_is_pinch_hitter")),
        **_fallback_metadata(data),
    }


def _fallback_metadata(data: dict) -> dict:
    """8秒ACK判定・Gemini Flash自動フォールバックの応答メタデータを導出する。
    fallback_triggered/engineはllmjp_is_pinch_hitterから(新規スキーマ列を
    追加しない既存フィールドの別名ビュー)、fallback_reasonはllmjp_fallback_reason
    (新設列、process_elyza_pinch_hitter()が"worker_ack_timeout"等を記録する)
    からそのまま返す。is_pinch_hitterはprocess_elyza_pinch_hitter()経由
    (ACKタイムアウト・完了タイムアウトいずれの代打分岐でも)でのみtrueになる。

    純粋関数として切り出し、get_status()を経由せず単体テストできるようにする。
    """
    is_fallback = bool(data.get("llmjp_is_pinch_hitter"))
    return {
        "fallback_triggered": is_fallback,
        "engine": "gemini-flash (fallback)" if is_fallback else "elyza",
        "fallback_reason": data.get("llmjp_fallback_reason") if is_fallback else None,
    }


@router.post("/generate")
@handle_exceptions
async def generate_ai(req: GenerateRequest, db=Depends(get_db)):
    doc_id = uuid.uuid4().hex
    # バッチ工場(batch/main.py)と同一フォーマットのDPOペアID。Gemini/ELYZA両パスの
    # ローカルDB更新へ記録し、抽出スクリプトがバッチ由来・アプリ由来を同一ロジックで
    # ペア回収できるようにする。
    pair_id = f"dpo-{uuid.uuid4().hex[:12]}"
    # 【2026-08-16改修: メイン画面のマイペルソナ/みんなのペルソナ対応】従来は
    # get_persona_or_raise(id, db)経由でビルトイン(int 1〜10)のみを解決していたが、
    # persona_generate.py::_resolve_persona_for_generation()を再利用し、
    # narrator_personas(マイペルソナ/みんなのペルソナ)も解決できるようにする。
    # ビルトイン優先(管理コクピットの動的上書きを反映)・存在しないIDは404、
    # という既存方針はこの関数内で維持されている(persona_generate.py参照)。
    # dbは両ルーターとも同じapi.deps.get_db()(Firestoreクライアント)を使うため
    # そのまま渡せる。
    resolved = _resolve_persona_for_generation(db, req.persona_id)
    # 【Phase5 §3.4レース対策の維持】ここで確定させたprompt文字列は、以降の
    # ELYZAジョブペイロード・SQLite行の両方へそのままスナップショットとして
    # 記録する(ワーカーはFirestoreを引き直さない)。_compose_persona_prompt()は
    # ビルトイン(name/promptの2キーのみ)に対してはprompt原文をそのまま返すため、
    # 既存の生成挙動を一切変えない。マイペルソナはtone/first_person等が追記され、
    # Gemini・ELYZA(おまけ)の両方に反映される。
    persona_prompt = _compose_persona_prompt(resolved.settings)
    narrator_persona_id = req.persona_id
    narrator_persona_version_id = resolved.version_id
    narrator_persona_name = resolved.display_name
    data_origin = resolved.data_origin
    await async_upsert_item(
        {
            "doc_id": doc_id,
            "odai": req.odai,
            "status": "processing",
            "eval_status": "processing",
            "llmjp_status": "pending",
            # 【Push型アーキテクチャ(2026-08-18)】elyza_job_status(オンデマンド
            # ワーカー用のジョブキュー合図)はもはや書かない。ELYZA(実機/代打)は
            # progressive_generate()内で直接完結するため、Firestore経由でclaimを
            # 待つ別プロセスは存在しない。
            "message": "AIが生成中...",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "random_weight": random.random(),  # noqa: S311 (無限スクロール用シーク乱数。暗号用途ではない)
            "dpo_pair_id": pair_id,
            # persona_feature_plan_v3.md Phase3で新設した論理参照4列。ビルトイン/
            # マイペルソナ双方の実際の解決結果を記録する("builtin"/"custom")。
            "narrator_persona_id": narrator_persona_id,
            "narrator_persona_version_id": narrator_persona_version_id,
            "narrator_persona_name": narrator_persona_name,
            "data_origin": data_origin,
            # persona列(既存のJSON汎用カラム)にリクエストされたペルソナID/温度を記録する。
            # 新規マイグレーション不要でスキーマへ組み込むための選択(監査・デバッグ用の
            # スナップショットとして保持)。【Push型アーキテクチャ移行後】process_elyza()は
            # このクロージャのpersona_prompt変数を直接使うため、生成そのものにはもう
            # このカラムを経由しない(旧workers/ondemand_elyza_worker.pyは現在
            # elyza_job_statusを一切受け取らなくなり事実上休止状態、_claim_job_sync
            # 経由でのみこの列を参照する)。
            "persona": {
                "persona_id": req.persona_id,
                "temperature": req.temperature,
                "narrator_persona_version_id": narrator_persona_version_id,
                "persona_prompt": persona_prompt,
            },
        }
    )
    # 【instructions/283】Cloud RunはCPUをリクエスト処理中のみ割り当てる仕様のため、
    # レスポンス送出後に実行されるBackgroundTasksはスケジュールされる保証が無く、
    # 同期が発火しないまま次のリクエストまでインスタンスがサスペンドされ得た
    # (instructions/282のFirestore同期欠落調査で判明)。書き込み直後、レスポンスを
    # 返す前に同期的に完了させることで、CPUが確実に割り当てられているリクエスト
    # 処理中に同期を完結させる。
    await sync_once_safe()

    # 【みんなの人気ペルソナAPI】マイペルソナ(data_origin=="custom")による生成
    # リクエストをusage_countとして計上する(persona_generate.py::generate_routed()と
    # 完全に同一の加算パターン)。narrator_personas.increment_usage_count()自体が
    # 失敗を内部で吸収するベストエフォート設計(カウンタ更新はなぞかけ生成自体の
    # 成否とは独立させる、という同関数のdocstring方針)のため、/api/generateの
    # 非同期(バックグラウンド生成)モデルにおいても、Gemini/ELYZAの実際の成否を
    # 待たずここで加算してよい。
    if data_origin == "custom":
        # 【ディープ監査#2】increment_usage_count()は同期関数でFirestoreへ
        # ブロッキングI/Oを行うため、asyncio.to_threadでラップしイベント
        # ループを塞がないようにする(persona_generate.py::generate_routed()と
        # 同じ対処)。
        await asyncio.to_thread(narrator_personas.increment_usage_count, db, narrator_persona_id)

    # 背景で生成パイプラインを発火し、即座にレスポンスを返す（HTTPをブロックしない）
    task = asyncio.create_task(
        _guarded_progressive(
            db, doc_id, req.odai, pair_id, persona_prompt, req.temperature, narrator_persona_id
        )
    )
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return {"status": "processing", "task_id": doc_id}
