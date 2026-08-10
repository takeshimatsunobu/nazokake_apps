"""生成ドメインルーター（Progressive Disclosure / 時間差おまけ生成）。

POST /generate        : お題を受け取り、生成を背景で発火して即座に task_id を返す（非ブロッキング）。
GET  /status/{doc_id} : 段階的ステータス（processing → gemini_completed → all_completed）をポーリングする。

フロー（生成と評価を分離）:
  1. Gemini 生成 → status:gemini_generated（本文先行）→ 評価 → status:gemini_completed
  2. 裏でELYZA 生成 → llmjp_status:generated（本文先行）→ 評価 → status:all_completed
     【instructions/258】ローカル開発(K_SERVICE未設定)では直接Ollamaを呼ぶ経路A。
     Cloud Run本番(K_SERVICE設定済み)ではLLMJP_URL等のトンネル設定が無く経路Aが
     構造的に到達不能なため試みず、generate_ai()が書き込むelyza_job_status経由の
     オンデマンドジョブキュー(instructions/250, workers/ondemand_elyza_worker.py)
     である経路Bにのみ委ねる。
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
from models.schemas import GenerateRequest
from personas import PERSONAS
from services.generation import generate_via_gemini, generate_via_llmjp
from services.evaluation import run_evaluation, AXES
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
            await async_record_evaluation_score("live_evaluation_gemini", ev["s_total"])
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

    async def process_elyza() -> None:
        """おまけパス: 生成→本文先行→評価→スコア。失敗は graceful に llmjp_status:failed。

        【instructions/258: 経路Aの到達不能修復】Cloud Run本番環境にはLLMJP_URL/
        CF_CLIENT_ID等のトンネル設定が存在せず(cloudbuild.yaml確認済み)、
        デフォルトのlocalhost:11434は構造的に到達不能(instructions/257で実測確認)。
        K_SERVICE(Cloud Run自身が注入する環境変数。main.pyのログ初期化と同じ検出規約)
        が設定されている場合はこの直接呼び出し自体を試みず、generate_ai()が既に
        書き込み済みのelyza_job_status="pending"を経由するinstructions/250の
        オンデマンドジョブキュー(workers/ondemand_elyza_worker.py)のみに委ねる
        (無駄な接続タイムアウトを避ける)。ローカル開発(K_SERVICE未設定)では
        従来通りこの直接呼び出しを試みる。
        """
        if os.getenv("K_SERVICE"):
            logger.info(
                f"[{doc_id}] ℹ️ Cloud Run環境のため直接ELYZA呼び出し(経路A)をスキップし、"
                "オンデマンドジョブキュー(経路B)に委ねます。"
            )
            return
        try:
            raw_result_l = await generate_via_llmjp(odai, persona_prompt, temperature)
            validated_result_l = _validate_result_with_fallback(
                raw_result_l, "生成結果の検証に失敗しました"
            )
            text_l = _compose_text(odai, validated_result_l)
            await async_upsert_item(
                {
                    "doc_id": doc_id,
                    "result_llmjp": validated_result_l,
                    "nazokake_text_llmjp": text_l,
                    "llmjp_status": "generated",
                    "message": "ELYZA作品を採点中...",
                    "dpo_pair_id": pair_id,
                }
            )
            ev_l = await run_evaluation(odai, text_l)
            # 【instructions/182】Gemini側(live_evaluation_gemini)とは別のpipeline_idで
            # 追跡する(ELYZA/おまけ側の不調がGemini側の健全なカウンタを汚さないため)。
            await async_record_evaluation_score(
                "live_evaluation_elyza", ev_l["s_total"]
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
            logger.exception(f"[{doc_id}] ELYZAパスで致命的エラー発生: {e}")
            await async_upsert_item(
                {
                    "doc_id": doc_id,
                    "llmjp_status": "failed",
                    "message": "おまけ生成中にエラーが発生しました",
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
):
    """未捕捉例外でもDBに必ず error を書き、無限ロード（サイレントデス）を防ぐ最終防壁。"""
    try:
        await progressive_generate(
            db, doc_id, odai, pair_id, persona_prompt, temperature
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


# 【instructions/250】オンデマンドELYZAワーカーがFirestoreへ書き戻す結果のうち、
# GET /status がマージしてよいフィールドのみを明示的に列挙する(スコープ限定)。
# status/eval_status/result/scores等のGemini・主系フィールドはここに含めない
# (SSoT §8.2の一方向同期原則への例外はこの狭いフィールド集合に限定されるため)。
# 【instructions/286】elyza_job_status自体もここに含める。フロントエンドが
# ポーリング終了判定に用いるため(以前は完了/失敗を問わずレスポンスに一切
# 含まれておらず、ローカルSQLiteにも反映されなかった)。
_ELYZA_JOB_MERGE_FIELDS = (
    "elyza_job_status",
    "llmjp_status",
    "result_llmjp",
    "nazokake_text_llmjp",
    "scores_llmjp",
    "s_total_llmjp",
    "overall_llmjp",
    "axis_comments_llmjp",
)


def _fetch_terminal_elyza_job_sync(doc_id: str) -> dict | None:
    """Firestoreの該当ドキュメントを直接読み取り、オンデマンドELYZAワーカーが
    elyza_job_statusを終端状態(completed または dead_letter。pending/processing
    以外)へ更新済みであれば、マージ対象フィールドのみを返す(読み取り専用。
    Cloud Run側からのFirestoreへの書き込みは一切行わない)。

    【instructions/286】以前は remote.get("elyza_job_status") == "completed" の
    場合のみ真としていたため、ジョブが dead_letter(恒久失敗)へ落ちた場合に
    永遠にマージされず、ローカルSQLiteのelyza_job_statusがpendingのまま残り、
    フロントエンドのポーリングが無限ループする不具合があった。

    firebase_adminの同期APIをそのまま使う(呼び出し元でasyncio.to_threadに包む)。
    """
    _ensure_firebase_app()
    db = firestore.client()
    snapshot = db.collection(_resolve_collection()).document(doc_id).get()
    if not snapshot.exists:
        return None
    remote = snapshot.to_dict() or {}
    if remote.get("elyza_job_status") in ("pending", "processing"):
        return None
    return {field: remote.get(field) for field in _ELYZA_JOB_MERGE_FIELDS}


async def _fetch_terminal_elyza_job(doc_id: str) -> dict | None:
    """Firestore参照が失敗しても(オフライン・権限エラー等)、ローカルSQLite単独の
    結果へ安全に縮退できるよう、例外はここで吸収してNoneを返す
    (呼び出し元のポーリングエンドポイント自体を落とさない)。
    """
    try:
        return await asyncio.to_thread(_fetch_terminal_elyza_job_sync, doc_id)
    except Exception as e:
        logger.warning(
            f"⚠️ [ELYZA Job] Firestoreからの結果マージに失敗(ローカルのみで続行): {e}"
        )
        return None


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

    # 【instructions/250→285】ローカルSQLite側にデータはあっても、オンデマンド
    # ELYZAワーカーがまだジョブを完了させていない(elyza_job_statusがpending/
    # processing等の未終端状態)場合、ワーカーがFirestoreへ直接書き込んだ最新の
    # 進捗(completed等)を能動的にPullし、ローカルSQLiteへ上書き同期してから
    # レスポンスを返す(llmjp_status=="completed"の場合は、ローカルの直接生成
    # パスで既に完結しているため、無駄なFirestore問い合わせを行わない)。
    if data.get("llmjp_status") != "completed" and data.get("elyza_job_status") in (
        "pending",
        "processing",
    ):
        elyza_job_result = await _fetch_terminal_elyza_job(doc_id)
        if elyza_job_result is not None:
            try:
                await async_upsert_item({"doc_id": doc_id, **elyza_job_result})
            except Exception as e:
                logger.warning(
                    f"⚠️ [ELYZA Job] Firestoreから取得した進捗のローカルSQLiteへの"
                    f"上書き同期に失敗(doc_id={doc_id}): {e}"
                )
            data = {**data, **elyza_job_result}

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
    }


@router.post("/generate")
@handle_exceptions
async def generate_ai(req: GenerateRequest, db=Depends(get_db)):
    doc_id = uuid.uuid4().hex
    # バッチ工場(batch/main.py)と同一フォーマットのDPOペアID。Gemini/ELYZA両パスの
    # ローカルDB更新へ記録し、抽出スクリプトがバッチ由来・アプリ由来を同一ロジックで
    # ペア回収できるようにする。
    pair_id = f"dpo-{uuid.uuid4().hex[:12]}"
    # ペルソナ選択(personas.py)。存在しないIDはデフォルト(1)にフォールバックする。
    persona_prompt = PERSONAS.get(req.persona_id, PERSONAS[1])["prompt"]
    await async_upsert_item(
        {
            "doc_id": doc_id,
            "odai": req.odai,
            "status": "processing",
            "eval_status": "processing",
            "llmjp_status": "pending",
            # 【instructions/250】オンデマンドELYZAワーカー用のジョブキュー合図。ここで
            # Firestoreへ直接書き込むことは絶対にしない(SSoT §8.2の一方向同期原則)。
            # この値は他フィールドと同様にローカルSQLiteへ書くだけであり、直後の
            # sync_once_safe(既存の一方向Push)が自動的にFirestoreへ伝播させる。
            "elyza_job_status": "pending",
            "message": "AIが生成中...",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "random_weight": random.random(),  # noqa: S311 (無限スクロール用シーク乱数。暗号用途ではない)
            "dpo_pair_id": pair_id,
            # persona列(既存のJSON汎用カラム)にリクエストされたペルソナID/温度を記録する。
            # 新規マイグレーション不要でスキーマへ組み込むための選択。
            "persona": {"persona_id": req.persona_id, "temperature": req.temperature},
        }
    )
    # 【instructions/283】Cloud RunはCPUをリクエスト処理中のみ割り当てる仕様のため、
    # レスポンス送出後に実行されるBackgroundTasksはスケジュールされる保証が無く、
    # 同期が発火しないまま次のリクエストまでインスタンスがサスペンドされ得た
    # (instructions/282のFirestore同期欠落調査で判明)。書き込み直後、レスポンスを
    # 返す前に同期的に完了させることで、CPUが確実に割り当てられているリクエスト
    # 処理中に同期を完結させる。
    await sync_once_safe()
    # 背景で生成パイプラインを発火し、即座にレスポンスを返す（HTTPをブロックしない）
    task = asyncio.create_task(
        _guarded_progressive(
            db, doc_id, req.odai, pair_id, persona_prompt, req.temperature
        )
    )
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return {"status": "processing", "task_id": doc_id}
