"""test_elyza_fallback_claim_guard.py
=======================================
改修要件: ELYZA 8秒ACK判定・Gemini Flash自動フォールバックの「二重実行防止」を
ワーカー側から検証する単体テスト。

apps/evaluator/backend/api/routers/generate.pyが8秒ACKタイムアウト時に
elyza_job_statusへ書き込む"cancelled"を、workers/ondemand_elyza_worker.pyの
claim判定ロジック(_is_claimable)が正しく拒否する(=claim対象から除外する)
ことを確認する。Firestore実サービスへは接続しない。
"""
from __future__ import annotations

import sys
from pathlib import Path

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
