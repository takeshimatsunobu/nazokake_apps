"""test_elyza_fallback_and_popular_personas.py
=================================================
改修要件: ELYZA 8秒ACK判定・Gemini Flash自動フォールバック、および
「みんなの人気ペルソナ」API(GET /v1/personas/popular)の単体テスト。

apps/evaluator/backend/test_fail_closed.py と同じ配置規約。
Firestore/Gemini実サービスへは接続しない(unittest.mock.patch / MagicMockで代替)。
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from api.routers.generate import _fallback_metadata, _wait_for_elyza_ack
from nazokake_core import narrator_personas


# ------------------------------------------------------------
# ELYZA 8秒ACK判定
# ------------------------------------------------------------


@pytest.mark.anyio
async def test_wait_for_elyza_ack_true_when_status_leaves_pending():
    """1回目はpending(未ACK)、2回目でprocessingへ遷移した場合、Trueで返る。"""
    statuses = iter(["pending", "processing"])

    async def fake_fetch(doc_id):
        return next(statuses)

    with patch("api.routers.generate._fetch_elyza_job_status", side_effect=fake_fetch):
        acked = await _wait_for_elyza_ack("doc-1", timeout_sec=10.0, poll_interval_sec=0.01)
    assert acked is True


@pytest.mark.anyio
async def test_wait_for_elyza_ack_false_on_timeout():
    """タイムアウトまでずっとpendingのままなら、Falseで返る(ワーカーオフライン判定)。"""

    async def fake_fetch(doc_id):
        return "pending"

    with patch("api.routers.generate._fetch_elyza_job_status", side_effect=fake_fetch):
        acked = await _wait_for_elyza_ack("doc-2", timeout_sec=0.05, poll_interval_sec=0.02)
    assert acked is False


@pytest.mark.anyio
async def test_wait_for_elyza_ack_false_when_doc_not_found():
    """ドキュメントが見つからない(None)場合もpending同然として扱い、Falseで返る。"""

    async def fake_fetch(doc_id):
        return None

    with patch("api.routers.generate._fetch_elyza_job_status", side_effect=fake_fetch):
        acked = await _wait_for_elyza_ack("doc-3", timeout_sec=0.05, poll_interval_sec=0.02)
    assert acked is False


# ------------------------------------------------------------
# fallback_triggered / engine メタデータ
# ------------------------------------------------------------


def test_fallback_metadata_when_pinch_hitter():
    result = _fallback_metadata({"llmjp_is_pinch_hitter": True, "llmjp_model_id": "gemini-3.5-flash-lite"})
    assert result == {"fallback_triggered": True, "engine": "gemini-flash (fallback)"}


def test_fallback_metadata_when_normal_elyza():
    result = _fallback_metadata({"llmjp_is_pinch_hitter": False, "llmjp_model_id": None})
    assert result == {"fallback_triggered": False, "engine": "elyza"}


def test_fallback_metadata_when_field_missing():
    """旧データ(llmjp_is_pinch_hitterキー自体が無い)でも安全にFalse側へ倒れる。"""
    result = _fallback_metadata({})
    assert result == {"fallback_triggered": False, "engine": "elyza"}


# ------------------------------------------------------------
# みんなの人気ペルソナ: narrator_personas側のロジック
# ------------------------------------------------------------


def test_list_popular_personas_sorts_by_usage_plus_zabuton():
    db = MagicMock()
    docs_data = [
        {"persona_id": "a", "is_builtin": False, "usage_count": 3, "zabuton_count": 1},
        {"persona_id": "b", "is_builtin": False, "usage_count": 1, "zabuton_count": 10},
        {"persona_id": "c", "is_builtin": False, "usage_count": 0, "zabuton_count": 0},
        {"persona_id": "d", "is_builtin": False, "deleted_at": "2026-01-01T00:00:00Z", "usage_count": 99, "zabuton_count": 99},
        {"persona_id": "e", "is_builtin": False, "is_visible": False, "usage_count": 50, "zabuton_count": 50},
    ]

    def _to_dict_factory(data):
        m = MagicMock()
        m.to_dict.return_value = data
        return m

    query = MagicMock()
    query.where.return_value = query
    query.stream.return_value = [_to_dict_factory(d) for d in docs_data]
    db.collection.return_value = query

    result = narrator_personas.list_popular_personas(db, limit=20)
    ids = [p["persona_id"] for p in result]
    # d(削除済み)・e(非表示)は除外され、b(11) > a(4) > c(0) の順。
    assert ids == ["b", "a", "c"]


def test_increment_usage_count_is_best_effort_on_failure():
    db = MagicMock()
    db.collection.return_value.document.return_value.update.side_effect = Exception("boom")
    # 例外を送出しないことのみを確認する(呼び出し元の生成レスポンスを道連れにしない)。
    narrator_personas.increment_usage_count(db, "some-id")
    narrator_personas.increment_zabuton_count(db, "some-id")
