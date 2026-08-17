"""本番503調査(2026-08-17)の回帰テスト。

main.py の _firestore_restore_gate ミドルウェアは、Cloud Run起動時の
Firestore復元(_firestore_restore_done)が完了するまで /api/* を503で
ガードする。このEvent/dictはプロセス内メモリのグローバル変数であり
Cloud Runの複数インスタンス間で共有されないため、「/api/healthはcompletedを
返すのに/api/generateは503のまま」という報告が発生した(詳細はmain.py内の
該当コメント参照)。

本テストは以下を検証する:
  1. 復元未完了でも POST /api/generate と GET /api/status/{doc_id} は
     ゲートの対象外として素通りする(復元対象データに依存しないため)。
  2. 復元未完了の状態で他の /api/* パス(例: /api/pending)は従来通り503。
  3. 復元処理がハングしても、タイムアウトにより _firestore_restore_done が
     確実にsetされる(永久503スタックのフェールセーフ)。
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_BACKEND_ROOT = Path(__file__).resolve().parent
_SHARED_CORE_ROOT = _PROJECT_ROOT / "packages" / "shared_core"
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))
if str(_SHARED_CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SHARED_CORE_ROOT))

import main  # noqa: E402  (sys.path設定後にimportする必要がある)


class _DummyRequest:
    def __init__(self, path: str):
        self.url = type("_U", (), {"path": path})()


async def _call_next_ok(request):
    return "downstream-called"


@pytest.mark.anyio
async def test_generate_bypasses_gate_while_restore_pending():
    """復元未完了(Event未set)でも /api/generate はゲートを素通りする。"""
    main._firestore_restore_done.clear()
    try:
        result = await main._firestore_restore_gate(
            _DummyRequest("/api/generate"), _call_next_ok
        )
        assert result == "downstream-called"
    finally:
        main._firestore_restore_done.set()


@pytest.mark.anyio
async def test_status_polling_bypasses_gate_while_restore_pending():
    """復元未完了でも /api/status/{doc_id} はゲートを素通りする
    (Firestoreへの能動フォールバックで自己完結するため)。"""
    main._firestore_restore_done.clear()
    try:
        result = await main._firestore_restore_gate(
            _DummyRequest("/api/status/abc123"), _call_next_ok
        )
        assert result == "downstream-called"
    finally:
        main._firestore_restore_done.set()


@pytest.mark.anyio
async def test_other_api_paths_still_gated_while_restore_pending():
    """/api/generate・/api/status/以外は従来通り復元完了までゲートされる。"""
    main._firestore_restore_done.clear()
    try:
        response = await main._firestore_restore_gate(
            _DummyRequest("/api/pending"), _call_next_ok
        )
        assert response.status_code == 503
        assert response.headers["Retry-After"] == "5"
    finally:
        main._firestore_restore_done.set()


@pytest.mark.anyio
async def test_other_api_paths_pass_once_restore_done():
    """復元完了(Event set)後は従来パスも素通りする(既存挙動の非破壊確認)。"""
    main._firestore_restore_done.set()
    result = await main._firestore_restore_gate(
        _DummyRequest("/api/pending"), _call_next_ok
    )
    assert result == "downstream-called"


@pytest.mark.anyio
async def test_hung_restore_times_out_and_releases_gate():
    """async_restore_from_firestore()がハングしても、タイムアウトにより
    _firestore_restore_done が確実にsetされ、永久503スタックを防ぐ。"""
    main._firestore_restore_done.clear()

    async def _hang_forever():
        await asyncio.sleep(3600)

    with (
        patch.object(main, "async_restore_from_firestore", AsyncMock(side_effect=_hang_forever)),
        patch.object(main, "_FIRESTORE_RESTORE_TIMEOUT_SECONDS", 0.05),
    ):
        await main._run_firestore_restore_in_background()

    assert main._firestore_restore_done.is_set()
    assert main._firestore_restore_status["state"] == "failed"
    main._firestore_restore_done.set()
