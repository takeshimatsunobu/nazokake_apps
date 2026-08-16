"""test_elyza_fallback_claim_guard.py
=======================================
改修要件: ELYZA 8秒ACK判定・Gemini Flash自動フォールバックの「二重実行防止」を
ワーカー側から検証する単体テスト。

apps/evaluator/backend/api/routers/generate.pyが8秒ACKタイムアウト時に
elyza_job_statusへ書き込む"cancelled"を、workers/ondemand_elyza_worker.pyの
claim判定ロジック(_is_claimable、第一防衛線)が正しく拒否する(=claim対象から
除外する)ことに加え、claim直後の再確認(_is_still_processing_sync、第二防衛線)
がclaim〜Ollama呼び出し開始までの間隙でのcancelled化も検知できることを
確認する。Firestore実サービスへは接続しない。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
for _p in (str(BASE_DIR), str(BASE_DIR / "workers"), str(BASE_DIR / "apps" / "evaluator" / "backend")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ondemand_elyza_worker as worker  # noqa: E402

_STALE_CUTOFF = "2026-01-01T00:00:00+00:00"


def test_cancelled_job_is_not_claimable():
    """フォールバックでcancelledへ書き換えられたジョブは、ワーカーが後から
    ポーリングしても二度とclaimされない(二重実行防止の核)。"""
    assert worker._is_claimable("cancelled", None, _STALE_CUTOFF) is False


def test_pending_job_is_claimable():
    assert worker._is_claimable("pending", None, _STALE_CUTOFF) is True


def test_fresh_processing_job_is_not_claimable():
    """他プロセスが最近claim済み(stale化していない)processingは奪わない。"""
    assert worker._is_claimable("processing", "2026-06-01T00:00:00+00:00", _STALE_CUTOFF) is False


def test_stale_processing_job_is_claimable():
    """15分超放置されたprocessing(ゾンビ化)は再claimしてよい。"""
    assert worker._is_claimable("processing", "2025-01-01T00:00:00+00:00", _STALE_CUTOFF) is True


def test_completed_and_dead_letter_jobs_are_not_claimable():
    assert worker._is_claimable("completed", None, _STALE_CUTOFF) is False
    assert worker._is_claimable("dead_letter", None, _STALE_CUTOFF) is False


def test_unknown_status_is_not_claimable():
    """将来追加され得る未知のステータス文字列も、allowlist方式のため安全側
    (claim不可)に倒れる。"""
    assert worker._is_claimable("some_future_status", None, _STALE_CUTOFF) is False
    assert worker._is_claimable(None, None, _STALE_CUTOFF) is False


# ------------------------------------------------------------
# 第二防衛線: claim直後、Ollama呼び出し直前の再確認(_is_still_processing_sync)
# ------------------------------------------------------------


def _make_snapshot(exists: bool, data: dict | None = None) -> MagicMock:
    snap = MagicMock()
    snap.exists = exists
    snap.to_dict.return_value = data
    return snap


def test_is_still_processing_sync_true_when_status_is_still_processing():
    db = MagicMock()
    db.collection.return_value.document.return_value.get.return_value = _make_snapshot(
        True, {"elyza_job_status": "processing"}
    )
    assert worker._is_still_processing_sync(db, "nazokake_items", "doc-1") is True


def test_is_still_processing_sync_false_when_cancelled_in_the_meantime():
    """claim直後にバックエンドがcancelledへ書き換えていた場合、Falseを返す
    (=呼び出し元はOllama呼び出しをスキップする)。"""
    db = MagicMock()
    db.collection.return_value.document.return_value.get.return_value = _make_snapshot(
        True, {"elyza_job_status": "cancelled"}
    )
    assert worker._is_still_processing_sync(db, "nazokake_items", "doc-1") is False


def test_is_still_processing_sync_false_when_doc_missing():
    db = MagicMock()
    db.collection.return_value.document.return_value.get.return_value = _make_snapshot(False, None)
    assert worker._is_still_processing_sync(db, "nazokake_items", "doc-1") is False


# ------------------------------------------------------------
# _process_job(): 第二防衛線が実際にGPU計算(generate_via_llmjp)をスキップ
# させることの結合テスト
# ------------------------------------------------------------


@pytest.mark.anyio
async def test_process_job_skips_ollama_call_when_cancelled_after_claim():
    """claim直後の再確認(_is_still_processing_sync)がFalseを返す場合、
    generate_via_llmjp(VRAM確保・Ollama推論)を一切呼び出さず、成功/失敗いずれの
    書き戻し(_mark_job_outcome/_mark_immediate_failure)も行わずスキップする
    (改修要件: 無駄なGPUバックログ処理の抑制)。"""
    db = MagicMock()
    job = {"doc_id": "doc-cancel-race", "odai": "お題", "dpo_pair_id": "dpo-1"}

    with patch("ondemand_elyza_worker._resolve_narrator_persona_fields", return_value={}), \
         patch("ondemand_elyza_worker._is_still_processing_sync", return_value=False), \
         patch("ondemand_elyza_worker.generate_via_llmjp", new=AsyncMock()) as mock_gen, \
         patch("ondemand_elyza_worker._mark_job_outcome", new=AsyncMock()) as mock_mark, \
         patch("ondemand_elyza_worker._mark_immediate_failure", new=AsyncMock()) as mock_fail:
        await worker._process_job(db, "nazokake_items", job)

    mock_gen.assert_not_awaited()
    mock_mark.assert_not_awaited()
    mock_fail.assert_not_awaited()


@pytest.mark.anyio
async def test_process_job_proceeds_to_ollama_when_still_processing():
    """再確認でまだ"processing"(=cancelledされていない)なら、通常どおり
    generate_via_llmjpを呼び出して処理を続行する(回帰確認)。"""
    db = MagicMock()
    job = {
        "doc_id": "doc-normal",
        "odai": "お題",
        "dpo_pair_id": "dpo-2",
        "persona_prompt_snapshot": "プロンプト",
    }

    with patch("ondemand_elyza_worker._resolve_narrator_persona_fields", return_value={}), \
         patch("ondemand_elyza_worker._is_still_processing_sync", return_value=True), \
         patch("ondemand_elyza_worker.generate_via_llmjp", new=AsyncMock(return_value={"toku": "解き"})) as mock_gen, \
         patch("ondemand_elyza_worker.run_evaluation", new=AsyncMock(return_value={"scores": {}, "s_total": 4.0, "overall": "ok", "axis_comments": {}})), \
         patch("ondemand_elyza_worker._mark_job_outcome", new=AsyncMock()) as mock_mark:
        await worker._process_job(db, "nazokake_items", job)

    mock_gen.assert_awaited_once()
    mock_mark.assert_awaited_once()
