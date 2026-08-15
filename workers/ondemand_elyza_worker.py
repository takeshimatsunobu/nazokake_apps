"""
workers/ondemand_elyza_worker.py
==================================
instructions/250: クラウド・ローカル連携によるオンデマンドELYZA生成ワーカー。

Cloud Run(本番)にはローカルのOllama/ELYZAへ到達する経路が(本番トンネルが常時
接続されていない限り)無いため、"おまけ"生成を即座に処理できない。本ワーカーは
Firestore経由の非同期メッセージングで、ユーザーのローカルGPUマシン上でELYZA生成・
評価を代行し、結果を書き戻す。

【split-brain回避のスコープ限定(SSoT §8.2 一方向同期原則への名前付き・限定的な例外)】
Cloud Run側は絶対にFirestoreへ直接書き込まない。「pending」の合図はCloud Run自身の
ローカルSQLite(apps/evaluator/backend、POST /generateの通常upsert)に書かれ、
既存の一方向同期(nazokake_core.firestore_sync.sync_once)が自動的にFirestoreへ
伝播させる(新規の書き込み経路を増やさない)。このワーカーだけが、以下の狭い
フィールド集合に限り、Firestoreへ直接書き込む権限を持つ第二の書き手として明示的に
許可される:
    elyza_job_status, elyza_job_locked_at, elyza_job_retry_count,
    llmjp_status, result_llmjp, nazokake_text_llmjp, scores_llmjp,
    s_total_llmjp, overall_llmjp, axis_comments_llmjp
status/eval_status/result/result_gemini/scores/message等のGemini・主系フィールドには
一切触れない。

使い方:
    uv run python workers/ondemand_elyza_worker.py                  # 1周期だけ実行
    uv run python workers/ondemand_elyza_worker.py --loop            # デーモンとして常駐
    uv run python workers/ondemand_elyza_worker.py --loop --interval 30
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import os
import signal
import sys
import time
import traceback
from pathlib import Path
from types import FrameType
from typing import Any

import filelock
import httpx

# Windowsの既定コンソールはcp932であり、print()で絵文字等を出力するとUnicodeEncodeError
# (最悪クラッシュ)や文字化けを起こす。apps/evaluator/backend/services/generation.py
# (このファイルが後段でimportする_load_fewshot_pool()が起動時に即printする)と同じ対策を、
# このファイル自身のprint(_log())が呼ばれるより前、かつどのimportよりも前に適用する。
if sys.platform == "win32":
    import io

    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    if isinstance(sys.stderr, io.TextIOWrapper):
        sys.stderr.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent.parent
# apps/evaluator/backend の services.generation / services.evaluation をそのまま
# 再利用するため(generate_via_llmjp / run_evaluationの再実装を避けるため)、
# そのディレクトリをsys.pathへ追加する。
BACKEND_DIR = BASE_DIR / "apps" / "evaluator" / "backend"
for _path in (BASE_DIR, BACKEND_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import firebase_admin  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from firebase_admin import firestore  # noqa: E402
from google.api_core.exceptions import GoogleAPICallError, RetryError  # noqa: E402

from nazokake_core import narrator_personas  # noqa: E402
from nazokake_core.database import async_upsert_item, ensure_db_ready  # noqa: E402
from nazokake_core.firestore_sync import (  # noqa: E402
    _ensure_firebase_app,
    _resolve_collection,
)
from nazokake_core.personas import get_persona_or_raise, get_personas  # noqa: E402
from services.evaluation import run_evaluation  # noqa: E402
from services.generation import (  # noqa: E402
    _try_acquire_vram_lock,
    _vram_lock,
    generate_via_llmjp,
)

# 【爆速化(1発入魂アルゴリズム)】本番はCloud Run→Firestoreジョブ作成→本ワーカーの
# ポーリング検知→生成→Firestore書き戻し→Cloud Runの再ポーリングという往復になる。
# クラウド側のタイムアウト(api/routers/generate.py::_ELYZA_WAIT_TIMEOUT_SEC)を
# 30〜35秒程度まで短縮したことに合わせ、「ジョブに気付くまでの最大待ち時間」を
# 極力削るためポーリング間隔も2秒まで縮めた。Firestoreの読み取りコストは増えるが、
# オンデマンドジョブの頻度自体が低いため許容する。
DEFAULT_POLL_INTERVAL_SEC = 2.0
CLAIM_BATCH_SIZE = 5
# ワーカークラッシュ等で"processing"のまま停止した場合のゾンビ回収閾値。
STALE_PROCESSING_TIMEOUT_SEC = 900  # 15分

# 【二重起動防止(Plan B)】scripts/start_elyza_worker.ps1側のOSプロセス一覧スキャン
# によるガードは、このラッパー経由での起動にしか効かず、直接実行や、ほぼ同時の
# 二重起動(両方がチェック時点では「まだ誰もいない」と判定するレースコンディション)
# を防げなかった(実機で複数の`ondemand_elyza_worker.py`プロセスが同じ.vram.lockを
# 奪い合う障害を確認済み)。起動経路を問わず構造的に二重起動を防ぐため、
# Pythonプロセス自身がfilelockでOSレベルの排他ロックを取得する。
_SINGLE_INSTANCE_LOCK_PATH = BASE_DIR / ".elyza_worker.pid.lock"

_ELYZA_JOB_SCOPED_FIELDS = frozenset(
    {
        "elyza_job_status",
        "elyza_job_locked_at",
        "elyza_job_retry_count",
        "llmjp_status",
        "result_llmjp",
        "nazokake_text_llmjp",
        "scores_llmjp",
        "s_total_llmjp",
        "overall_llmjp",
        "axis_comments_llmjp",
    }
)

_shutdown_requested = False


def _log(message: str) -> None:
    """稼働ログをsys.stdoutへ出力する(tools/scheduler_daemon.pyと同じ規約:
    異常系のトレースバックはsys.stderrへ厳格に分離する)。"""
    print(f"[ondemand_elyza_worker] {message}", file=sys.stdout, flush=True)


def _handle_shutdown_signal(signum: int, frame: FrameType | None) -> None:
    """SIGTERM/SIGINT受信時、直ちに終了せずフラグを立てる(Graceful Shutdown、
    tools/scheduler_daemon.pyと同じパターン)。"""
    global _shutdown_requested
    _log(f"🛑 シグナル{signum}を受信しました。Graceful Shutdownします...")
    _shutdown_requested = True


def _interruptible_sleep(seconds: float) -> None:
    """_shutdown_requestedを1秒間隔でポーリングしながらsleepする
    (tools/scheduler_daemon.pyと同じ理由: PEP 475によりtime.sleep()単体では
    シグナル受信後も最大`seconds`秒待たされてしまうため)。"""
    deadline = time.monotonic() + seconds
    while not _shutdown_requested and time.monotonic() < deadline:
        time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _compose_text(odai: str, result: dict) -> str:
    """apps/evaluator/backend/api/routers/generate.py::_compose_text と同一ロジック。
    workers/からapps/evaluator/backendの内部ヘルパーを直接importするのは越境
    しすぎるため、この1関数だけ意図的に複製する。
    """
    return f"「{odai}」とかけて、「{result.get('toku', '')}」と解く。\nその心は、{result.get('kokoro', '')}"


_NARRATOR_PERSONA_FALLBACK: dict[str, str] = {
    "narrator_persona_id": "No_Data",
    "narrator_persona_version_id": "No_Data",
    "narrator_persona_name": "No_Data",
    "data_origin": "no_data",
}


def _resolve_narrator_persona_fields(
    db, persona_id: Any, version_id_snapshot: str | None
) -> dict[str, str]:
    """narrator_persona_id/_version_id/_name/data_originの4列値を解決する。

    【既知のギャップ(docs/persona_feature_plan_v3.md §12)の恒久対応】
    apps/evaluator/backend/api/routers/generate.py::generate_ai()は、なぞかけ
    生成リクエストを受けた"最初の書き込み"の時点でこの4列を設定するが、それは
    Cloud Run自身の一時SQLite(`/tmp`、インスタンス終了で消える)に対してであり、
    このワーカーが動くローカルマシンの`nazokake_local.db`とは別ファイルである。
    ワーカーがジョブをclaimする段階では、そのdoc_idはワーカー側ローカルDBに
    まだ一度も存在しないため、_mark_job_outcome()のasync_upsert_item()は
    新規行として挿入する(upsert_item()のexisting is Noneの枝)。その際に渡す
    payloadにこの4列が含まれていなければ、スキーマのserver_default("No_Data"/
    "no_data")のまま記録され続けてしまう。さらにFirestore側の"persona"スナップ
    ショット(_claim_job_sync参照)にはnarrator_persona_name/data_originが
    元々含まれていないため、ワーカー側で改めて解決する必要がある。

    generate_ai()と同じ規約(narrator_persona_id=str(persona_id)、
    narrator_persona_version_idはnazokake_core.narrator_personas.compute_version_id
    の内容ハッシュ形式、data_originは"builtin"/"custom"/"no_data")に揃える。

    【安全策】persona_idが未指定・不正・解決不能ないずれの場合も例外を送出せず、
    "No_Data"/"no_data"へフォールバックする(このワーカー自体をクラッシュさせない
    ための安全策。呼び出し元のtry節がさらに全体を覆っているが、ここでも二重に
    防御する)。
    """
    if persona_id is None:
        return dict(_NARRATOR_PERSONA_FALLBACK)

    try:
        # ビルトイン("1"〜"10"): get_personas(db)経由(管理コクピットの動的
        # 上書きを反映、generate_ai()と同じ経路)。
        try:
            numeric_id = int(persona_id)
        except (TypeError, ValueError):
            numeric_id = None

        if numeric_id is not None:
            builtin = get_personas(db).get(numeric_id)
            if builtin is not None:
                resolved_id = str(numeric_id)
                version_id = version_id_snapshot or narrator_personas.compute_version_id(
                    resolved_id,
                    {"display_name": builtin["name"], "prompt": builtin["prompt"]},
                )
                return {
                    "narrator_persona_id": resolved_id,
                    "narrator_persona_version_id": version_id,
                    "narrator_persona_name": builtin["name"],
                    "data_origin": "builtin",
                }

        # マイペルソナ(UUID文字列): 現時点でapps/evaluator/frontendはビルトイン
        # のみを送信する想定だが、将来ここ経由でも選択可能になった場合の保険として
        # 対応しておく(apps/persona_main_function/api/routers/generate.py::
        # _resolve_persona_for_generationと同じ二段構え)。
        custom = narrator_personas.get_persona(db, str(persona_id))
        if custom is not None and not custom.get("deleted_at"):
            return {
                "narrator_persona_id": str(persona_id),
                "narrator_persona_version_id": (
                    version_id_snapshot or custom.get("current_version_id") or "No_Data"
                ),
                "narrator_persona_name": custom.get("display_name") or "No_Data",
                "data_origin": "custom",
            }
    except Exception as e:
        _log(f"⚠️ narrator_persona情報の解決に失敗しました(No_Dataへフォールバックします): {e}")

    return dict(_NARRATOR_PERSONA_FALLBACK)


def _stale_cutoff_iso() -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(seconds=STALE_PROCESSING_TIMEOUT_SEC)
    ).isoformat()


def _find_claimable_doc_ids(db, collection: str) -> list[str]:
    """pending、またはstaleなprocessing(ゾンビ)のdoc_idを取得する(読み取りのみ、
    このクエリ自体はまだ何も書き込まない)。"""
    stale_cutoff = _stale_cutoff_iso()

    pending_docs = (
        db.collection(collection)
        .where(filter=firestore.FieldFilter("elyza_job_status", "==", "pending"))
        .limit(CLAIM_BATCH_SIZE)
        .stream()
    )
    stale_docs = (
        db.collection(collection)
        .where(filter=firestore.FieldFilter("elyza_job_status", "==", "processing"))
        .where(filter=firestore.FieldFilter("elyza_job_locked_at", "<", stale_cutoff))
        .limit(CLAIM_BATCH_SIZE)
        .stream()
    )
    doc_ids: list[str] = []
    seen: set[str] = set()
    for doc in list(pending_docs) + list(stale_docs):
        if doc.id not in seen:
            seen.add(doc.id)
            doc_ids.append(doc.id)
    return doc_ids


def _claim_job_sync(db, collection: str, doc_id: str) -> dict[str, Any] | None:
    """対象ドキュメントをトランザクションで排他的に"processing"へ遷移させる
    (firestore_sync._push_one_syncと同じread-then-writeのアトミック性)。

    再読込時点でpending/staleの条件を満たさなくなっていた場合(別プロセスに
    先に取られた等)はNoneを返してスキップする。
    """
    doc_ref = db.collection(collection).document(doc_id)
    stale_cutoff = _stale_cutoff_iso()

    # google-cloud-firestoreの型スタブがtransactionalを宣言していないためのfalse
    # positive(実行時には存在する。board.pyの同一パターンで動作確認済み)。
    @firestore.transactional  # pyright: ignore[reportAttributeAccessIssue]
    def _txn(transaction) -> dict[str, Any] | None:
        snapshot = doc_ref.get(transaction=transaction)
        if not snapshot.exists:
            return None
        remote = snapshot.to_dict() or {}
        status = remote.get("elyza_job_status")
        locked_at = remote.get("elyza_job_locked_at")
        claimable = status == "pending" or (
            status == "processing"
            and (locked_at is None or locked_at < stale_cutoff)
        )
        if not claimable:
            return None
        transaction.update(
            doc_ref,
            {"elyza_job_status": "processing", "elyza_job_locked_at": _now_iso()},
        )
        # persona/temperature: POST /generate 側がpersona列(汎用JSONカラム)に
        # {"persona_id":.., "temperature":..} として書き込み済み(instructions/
        # generate.py::generate_ai)。ユーザーが選んだペルソナ・温度をELYZA側の
        # 生成にも反映するため、ここで一緒に読み取る。欠落時はデフォルトへ安全に
        # フォールバックする(旧データ・persona未選択時)。
        persona_meta = remote.get("persona") if isinstance(remote.get("persona"), dict) else {}
        return {
            "doc_id": doc_id,
            "odai": remote.get("odai") or "",
            "retry_count": remote.get("elyza_job_retry_count") or 0,
            # 【instructions/251】DPO抽出がGemini/ELYZA両起源のレコードを同一ペアとして
            # 回収できるよう、元ドキュメントのdpo_pair_idを引き継ぐ。Firestore側には
            # Cloud Run自身の元のPushで既に正しく書き込まれているため、ここで
            # スコープ付きFirestore書き込み(_ELYZA_JOB_SCOPED_FIELDS)には含めない
            # (含めるとスコープ外フィールドとしてガードに拒否される)。ワーカー自身の
            # ローカルSQLite側の記録にのみ必要。
            "dpo_pair_id": remote.get("dpo_pair_id"),
            "persona_id": persona_meta.get("persona_id"),
            "temperature": persona_meta.get("temperature"),
            # 【persona_feature_plan_v3.md Phase5 §3.4: レース対策】投入時点で
            # 確定させたversion_id/プロンプト本文のスナップショット。投入から実行
            # までの間に管理者がペルソナを編集し得るため、ワーカーはFirestoreを
            # 引き直さずこのスナップショットを優先的に使う(_process_job参照)。
            # 旧形式のジョブ(このスナップショットが導入される前に投入された
            # ジョブ)にはこれらのキー自体が存在しないため、.get()はNoneを返す
            # (=_process_job側のフォールバックで動的取得に切り替わる)。
            "narrator_persona_version_id": persona_meta.get("narrator_persona_version_id"),
            "persona_prompt_snapshot": persona_meta.get("persona_prompt"),
        }

    return _txn(db.transaction())


def _write_scoped_fields_sync(
    db, collection: str, doc_id: str, fields: dict[str, Any]
) -> None:
    """狭いフィールド集合のみをFirestoreへ書き戻す(doc_ref.update、非merge set()は
    使わない)。予期しないキーが紛れ込んでいないか、書き込み直前に防御的に検証する。
    """
    unexpected = set(fields) - _ELYZA_JOB_SCOPED_FIELDS
    if unexpected:
        raise ValueError(
            f"スコープ外のフィールドへの書き込みを検知したため中止します: {unexpected}"
        )
    db.collection(collection).document(doc_id).update(fields)


async def _mark_job_outcome(
    db,
    collection: str,
    doc_id: str,
    odai: str,
    *,
    local_fields: dict[str, Any],
    scoped_fields: dict[str, Any],
) -> None:
    """成功/失敗いずれの結果も、ワーカー自身のローカルSQLite(instructions/250
    Step 3.3)とFirestoreの両方へ書く。ローカルSQLiteはワーカー専用の別ファイルで
    あり、doc_idが未知の場合は新規行としてINSERTされる(odaiはNOT NULL制約のため
    必須)。
    """
    await async_upsert_item({"doc_id": doc_id, "odai": odai, **local_fields})
    await asyncio.to_thread(
        _write_scoped_fields_sync, db, collection, doc_id, scoped_fields
    )
async def _process_job(db, collection: str, job: dict[str, Any]) -> None:
    import sys
    import traceback

    doc_id = job['doc_id']
    odai = job['odai']
    dpo_pair_id = job.get('dpo_pair_id')
    temperature = job.get('temperature')
    # 【docs/persona_feature_plan_v3.md §12既知ギャップの恒久対応】このワーカー
    # 自身のローカルSQLiteにも4列を記録できるよう、成功/失敗いずれの書き戻し
    # パスでも使えるようここで一度だけ解決する(_resolve_narrator_persona_fields
    # 自体は例外を送出せず安全にフォールバックする)。
    narrator_fields = _resolve_narrator_persona_fields(
        db, job.get('persona_id'), job.get('narrator_persona_version_id')
    )

    if not odai:
        _log(f'⚠️ [{doc_id}] odaiが空のため生成をスキップし、即時失敗として扱います。')
        await _mark_immediate_failure(
            db, collection, doc_id, odai, dpo_pair_id, 'odai is empty', narrator_fields
        )
        return

    # 【1発入魂アルゴリズム(爆速化)】best-of-3(N=3並行生成→最高得点選抜)を廃止し、
    # 1回の生成のみを試みる。出力スキーマ不正時のリトライはgenerate_via_llmjp内部
    # (_MAX_OUTPUT_RETRIES、最大3回)が担う。ここでの失敗は「1発入魂+内部リトライを
    # 尽くしてもダメだった」ことを意味するため、次のポーリング周期への再キュー
    # (pending化)は行わず、即座にterminal failedとして書き戻す。これにより
    # クラウド側(process_elyza_pinch_hitter)の代打判断を速やかに発火させられる。
    # 【多重防御・第一防衛線】生成(Gemini/ELYZA)・評価(Gemini)・成功時の書き戻し
    # (Firestore)のいずれの段階で例外が発生しても(型を問わず)、このtry1本で
    # 受け止め、ジョブをfailedとして確定させてプロセス自体はクラッシュさせない。
    # 以前は成功時の書き戻し(_mark_job_outcome)がこのtryの外にあり無防備だった。
    try:
        # 【persona_feature_plan_v3.md Phase5 §3.4: レース対策】投入時点で確定させた
        # プロンプト本文のスナップショットが含まれていれば、それを最優先で使う
        # (Firestoreを引き直さない=投入後に管理者がペルソナを編集してもこの
        # ジョブの結果は変わらない)。
        # 【フォールバック】スナップショットが無い旧形式のジョブ(この機能導入前に
        # 投入されたジョブ)に限り、Phase4のget_persona_or_raise(id, db)で動的に
        # 取得する(管理コクピットの上書きを反映、存在しないIDはPersonaNotFoundError
        # →このtryのexcept節(第一防衛線、_mark_immediate_failure)を通じて即時
        # failedとして確定させる。記録上のpersona_idと実際に使われたペルソナが
        # 食い違う事故を防ぐため、PERSONAS[1]への黙ったフォールバックはしない)。
        persona_prompt = job.get('persona_prompt_snapshot')
        if persona_prompt:
            _log(
                f"[{doc_id}] 📌 プロンプトスナップショットを使用します"
                f"(narrator_persona_version_id={job.get('narrator_persona_version_id')})。"
            )
        else:
            _log(f"[{doc_id}] ⚠️ スナップショットが無い旧形式のジョブのため、動的に取得します。")
            persona = get_persona_or_raise(job.get('persona_id'), db)
            persona_prompt = persona['prompt']

        raw_result = await generate_via_llmjp(odai, persona_prompt, temperature)
        text = _compose_text(odai, raw_result)
        evaluation = await run_evaluation(odai, text)

        fields = {
            'result_llmjp': raw_result,
            'nazokake_text_llmjp': text,
            'scores_llmjp': evaluation['scores'],
            's_total_llmjp': evaluation['s_total'],
            'overall_llmjp': evaluation['overall'],
            'axis_comments_llmjp': evaluation['axis_comments'],
            'llmjp_status': 'completed',
            'elyza_job_status': 'completed',
            'elyza_job_locked_at': None,
            'elyza_job_retry_count': 0
        }
        # 【重要】narrator_persona_*の4列はscoped_fields(Firestore、_ELYZA_JOB_SCOPED_FIELDS
        # の厳格な許可リストを持つ)には含めない。Firestore側は既にgenerate_ai()の
        # 最初の書き込みで正しい値を持っているため触れる必要が無く、含めると
        # _write_scoped_fields_syncがスコープ外フィールドとして例外を送出する。
        # local_fields(このワーカー自身のローカルSQLite)にのみ追加する。
        await _mark_job_outcome(
            db, collection, doc_id, odai,
            local_fields={**fields, 'dpo_pair_id': dpo_pair_id, **narrator_fields},
            scoped_fields=fields,
        )
        _log(f'✅ [{doc_id}] ELYZA生成・評価・Firestore書き戻しが完了しました。')
    except Exception as e:
        _log(f'⚠️ [{doc_id}] ELYZA処理に失敗したため、即時failedとして書き戻します: {e}')
        traceback.print_exc(file=sys.stderr)
        try:
            await _mark_immediate_failure(
                db, collection, doc_id, odai, dpo_pair_id, str(e), narrator_fields
            )
        except Exception as mark_err:
            # 【最終防衛ライン】failed状態への書き戻し自体が失敗した場合(例:
            # 元の失敗原因がFirestoreへの通信不能そのものだった場合)も、ここで
            # 握りつぶしログのみ出して必ずreturnする。ここから先へは例外を
            # 一切伝播させない。
            _log(f'⚠️ [{doc_id}] failed状態への書き戻しにも失敗しました(無視して続行します): {mark_err}')


async def _mark_immediate_failure(
    db,
    collection: str,
    doc_id: str,
    odai: str,
    dpo_pair_id: str | None,
    error_message: str,
    narrator_fields: dict[str, str] | None = None,
) -> None:
    """【爆速化】1発入魂+内部リトライ(generate_via_llmjpの_MAX_OUTPUT_RETRIES)を
    尽くしてもELYZA生成が成立しなかった場合、次のポーリング周期での"pending"再
    キューを待たず、即座にterminal(dead_letter/failed)として書き戻す。

    以前の_mark_failure()は指数バックオフ無しの単純な"pending"再キューを
    MAX_JOB_RETRIES(3)回繰り返す設計だったが、これは「クラウド側の代打判断が
    ワーカー側の再試行完了まで待たされる」という、今回の爆速化の目的(クラウド側
    タイムアウトを30〜35秒へ短縮)と相反する遅延要因だった。ジョブレベルの
    再キューを廃し、失敗はここで一度確定させる(それでもユーザー体験としては
    クラウド側がGemini Flash Liteへ即座に代打させるため、失敗が露呈することはない)。

    narrator_fields: _resolve_narrator_persona_fields()の解決結果。呼び出し元が
    未解決のまま渡してきた場合(呼び出しがodai空チェック等、persona解決より前の
    早期リターン経路の場合)も、安全にNo_Data側へフォールバックする。
    """
    fields: dict[str, Any] = {
        "elyza_job_status": "dead_letter",
        "elyza_job_locked_at": None,
        "llmjp_status": "failed",
    }
    _log(f"📮 [{doc_id}] ELYZA生成に失敗したため即時dead_letterとしました: {error_message}")

    await _mark_job_outcome(
        db,
        collection,
        doc_id,
        odai,
        local_fields={
            **fields,
            "dpo_pair_id": dpo_pair_id,
            **(narrator_fields or _NARRATOR_PERSONA_FALLBACK),
        },
        scoped_fields=fields,
    )


async def run_once() -> int:
    """1周期分: claim可能なジョブを列挙し、1件ずつ順番に処理する。戻り値は処理件数。

    同時に複数ジョブを並行処理しない(generate_via_llmjp内部の_OLLAMA_SEMAPHOREが
    どのみち同時1リクエストへ制限するため、ここで並行化する意味がない)。
    """
    _ensure_firebase_app()
    db = firestore.client()
    collection = _resolve_collection()

    doc_ids = await asyncio.to_thread(_find_claimable_doc_ids, db, collection)
    processed = 0
    for doc_id in doc_ids:
        job = await asyncio.to_thread(_claim_job_sync, db, collection, doc_id)
        if job is None:
            continue  # 既に他の実行に取られていた、または条件を満たさなくなっていた
        _log(f"🎯 [{doc_id}] ジョブをclaimしました(odai='{job['odai']}')。")
        try:
            await _process_job(db, collection, job)
        except Exception as e:
            # 【多重防御・第二防衛線】_process_job内部の防御(第一防衛線)が万一
            # 機能しなかった場合でも、1件のジョブの例外で残りのdoc_idsの処理や
            # デーモンプロセス自体を道連れにしない。
            _log(f"⚠️ [{doc_id}] ジョブ処理で予期しない例外が発生しました(次のジョブへ続行します): {e}")
            traceback.print_exc(file=sys.stderr)
        processed += 1
    return processed


def _diagnose_vram_lock() -> None:
    """起動時のVRAMロック診断(セルフヒーリング)。

    services.generation の_vram_lockをそのまま再利用し、非ブロッキングで
    取得→即releaseを試みるだけの「診断」であり、強制解除は行わない。
    tools/mlops_pipeline_*.py 等、他の正当なプロセスが実際に保持している
    可能性があるため、ここで奪い取ることはしない(取得できなければ警告
    ログを出すのみ)。
    """
    try:
        if _try_acquire_vram_lock():
            _vram_lock.release()
            _log("🔍 [起動診断] VRAMロックは現在誰も保持していません。")
        else:
            _log(
                "⚠️ [起動診断] VRAMロックは他プロセス(MLOpsパイプライン等)が"
                "保持中の可能性があります。ELYZA生成が一時的に失敗しても想定内です。"
            )
    except Exception as e:
        _log(f"⚠️ [起動診断] VRAMロックの診断に失敗しました(無視して続行します): {e}")


def _check_ollama_reachable() -> None:
    """起動時のOllamaエンドポイント疎通確認(セルフヒーリング)。

    失敗しても起動は止めない(警告ログのみ)。あくまで診断目的。
    """
    url = os.environ.get("LLMJP_URL", "http://localhost:11434/v1/chat/completions")
    base = url.split("/v1/")[0]
    try:
        httpx.get(base, timeout=3.0)
        _log(f"🔍 [起動診断] Ollamaエンドポイント({base})への疎通を確認しました。")
    except Exception as e:
        _log(f"⚠️ [起動診断] Ollamaエンドポイント({base})に疎通できませんでした: {e}")


def _reclaim_stale_jobs_on_startup(db, collection: str) -> None:
    """未完了ジョブの即時救済(セルフヒーリング)。

    【呼び出し条件・厳守】.elyza_worker.pid.lock(単一インスタンス保証)を取得した
    直後、かつメインループ開始前にのみ呼び出すこと。単一インスタンスであることが
    確定しているため、この時点でelyza_job_status=="processing"のジョブが存在
    すれば、それは前回インスタンスの異常終了(exit=-1等)による残留と断定でき、
    _find_claimable_doc_idsの15分の経過待ち(STALE_PROCESSING_TIMEOUT_SEC)を
    待たず即座にpendingへ復帰させて良い。この前提(単一インスタンス確定後にのみ
    呼ぶこと)が崩れると、並行稼働中の別インスタンスが処理中の正当なジョブを
    誤って奪ってしまうため、呼び出し元を変更しないこと。
    """
    try:
        docs = list(
            db.collection(collection)
            .where(filter=firestore.FieldFilter("elyza_job_status", "==", "processing"))
            .stream()
        )
    except Exception as e:
        _log(f"⚠️ [起動救済] 残留ジョブの検索に失敗しました(無視して続行します): {e}")
        return

    reclaimed = 0
    for doc in docs:
        try:
            _write_scoped_fields_sync(
                db,
                collection,
                doc.id,
                {"elyza_job_status": "pending", "elyza_job_locked_at": None},
            )
            reclaimed += 1
        except Exception as e:
            _log(f"⚠️ [起動救済] [{doc.id}] pendingへの復帰に失敗しました: {e}")

    if reclaimed:
        _log(
            f"🩹 [起動救済] 前回異常終了の残留と見られるジョブを{reclaimed}件、"
            "pendingへ即時復帰しました。"
        )


def _startup_self_heal(db, collection: str) -> None:
    """起動時セルフヒーリングの入口(診断2種+即時救済1種)。

    【呼び出し条件・厳守】_reclaim_stale_jobs_on_startupの制約を引き継ぎ、
    --loopモードで.elyza_worker.pid.lockを取得した直後にのみ呼び出すこと。
    """
    _log("🩺 起動時セルフヒーリングを実行します...")
    _diagnose_vram_lock()
    _check_ollama_reachable()
    _reclaim_stale_jobs_on_startup(db, collection)


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="On-demand ELYZA generation worker (Firestore job queue, instructions/250)"
    )
    p.add_argument(
        "--loop", action="store_true", help="1周期で終了せず、intervalごとに繰り返し実行する"
    )
    p.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_POLL_INTERVAL_SEC,
        help="--loop時のポーリング間隔(秒)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    load_dotenv()

    # main.py(apps/evaluator/backend)と同じ固定projectIdでFirebase Admin SDKを初期化する。
    # 【instructions/250】_ensure_firebase_app()(nazokake_core.firestore_sync)はGCP上の
    # デフォルト認証情報からproject_idを自動解決できる場合のみ動作するが、ローカルGPU機
    # (このワーカーの実行環境)ではGOOGLE_CLOUD_PROJECT等が設定されておらず、
    # "ValueError: Project ID is required to access Firestore" で即クラッシュする。
    # ここで先に明示的なprojectId付きでinitialize_app()しておけば、
    # _ensure_firebase_app()の `if not firebase_admin._apps:` ガードにより
    # 後続のproject_id自動解決は一切試みられず、安全にスキップされる。
    if not firebase_admin._apps:
        firebase_admin.initialize_app(options={"projectId": "nazokakeapp-137e5"})

    ensure_db_ready()

    if not args.loop:
        processed = asyncio.run(run_once())
        _log(f"1周期完了({processed}件処理)。")
        return 0

    # 【二重起動防止(Plan B)】非ブロッキング(timeout=0)でOSレベルの排他ロックを
    # 取得する。既に別プロセス(直接実行・start_elyza_worker.ps1経由・二重起動の
    # レースコンディション等、起動経路を問わない)が保持中であれば、即座に
    # exit 0する(エラー扱いにはしない。呼び出し元のラッパーが「異常終了」と誤認して
    # 再起動ループへ入らないようにするため)。
    instance_lock = filelock.FileLock(str(_SINGLE_INSTANCE_LOCK_PATH), timeout=0)
    try:
        instance_lock.acquire()
    except filelock.Timeout:
        _log("既に別プロセスが稼働中のため終了します")
        sys.exit(0)

    try:
        signal.signal(signal.SIGTERM, _handle_shutdown_signal)
        signal.signal(signal.SIGINT, _handle_shutdown_signal)
        _log(f"デーモンとして起動しました(ポーリング間隔: {args.interval}秒)。")

        # 【セルフヒーリング・呼び出し条件】instance_lock(.elyza_worker.pid.lock)を
        # 取得済み=単一インスタンスであることが確定した、このタイミングでのみ
        # _startup_self_heal(内部の_reclaim_stale_jobs_on_startup)を呼び出す。
        # メインループ開始前のこの1箇所以外から呼ばないこと。
        _ensure_firebase_app()
        _startup_self_heal(firestore.client(), _resolve_collection())

        while not _shutdown_requested:
            try:
                processed = asyncio.run(run_once())
                if processed:
                    _log(f"{processed}件処理しました。")
            except (RetryError, GoogleAPICallError, TimeoutError, ConnectionError) as e:
                # 【通信エラーからの自己復帰】Firestoreへのポーリング(_find_claimable_doc_ids/
                # _claim_job_sync)がネットワークの瞬断やNorton等のTLS中間者検査の影響で
                # RetryError/GoogleAPICallError(gRPC接続タイムアウト等)を送出すると、
                # 以前はこの周期の例外がそのままプロセスをクラッシュさせ、
                # start_elyza_worker.ps1の自動再起動ループに丸ごと頼る形になっていた
                # (実機ログで`exit=-1`からの15秒後再起動を確認済み)。ここで明示的に
                # 捕捉し、短い待機を挟んでループを継続することで、プロセス再起動という
                # 重い手段を経ずに次のポーリング周期で自己復帰できるようにする。
                _log(f"⚠️ 通信エラーにより再試行します: {e}")
                _interruptible_sleep(5.0)
                continue
            except Exception:
                # 1周期の失敗でデーモン自体を落とさない(tools/scheduler_daemon.pyと同じ規約)。
                traceback.print_exc(file=sys.stderr)
            _interruptible_sleep(args.interval)
        _log("Graceful Shutdown完了。")
        return 0
    finally:
        instance_lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
