"""本番調査(2026-08-18)の回帰テスト。

ELYZAオンデマンドワーカーが「常に8秒ACKタイムアウトでGemini Flash代打になる」
障害の根本原因は、packages/shared_core/nazokake_core/firestore_sync.py の
_build_push_payload() が、Cloud Run自身の正当な elyza_job_status:
"pending"→"cancelled" 更新(8秒ACKタイムアウト確定時)まで一律に
「ワーカー所有フィールドだから上書きしない」として除外し、Firestoreへ
"cancelled"が届かないまま永久に"pending"が残ってしまうことだった(本番
Firestoreで実際に15件のゾンビpendingジョブを確認、うち10件は既に
Gemini代打で回答済み)。

本テストは、この修正後の_build_push_payload()の挙動を検証する:
  1. 新規ドキュメント(remote_data=None)では従来通りローカル値がそのまま入る。
  2. リモートがまだ"pending"(ワーカー未claim)の間は、Cloud Run自身の
     "cancelled"更新がpayloadから除外されない(=Firestoreへ届く)。
  3. リモートが"processing"/"completed"等(ワーカーが既にclaim/進行済み)の
     場合は、従来通りローカルの陳腐化した値で上書きされないよう保護される。
  4. elyza_job_locked_at/elyza_job_retry_count(Cloud Runは一切書かない
     フィールド)は、リモートに値がありさえすれば従来通り常に保護される。
"""

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SHARED_CORE_ROOT = _PROJECT_ROOT / "packages" / "shared_core"
if str(_SHARED_CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SHARED_CORE_ROOT))

from nazokake_core.firestore_sync import _build_push_payload  # noqa: E402


def test_new_document_includes_all_fields_unmodified():
    row = {"doc_id": "abc", "odai": "テスト", "elyza_job_status": "pending"}
    payload = _build_push_payload(row, remote_data=None)
    assert payload == row


def test_cancelled_write_reaches_firestore_while_remote_still_pending():
    """8秒ACKタイムアウト時、Cloud Run自身の"cancelled"書き込みが
    リモートまだ"pending"の間は除外されない(=Firestoreへ届く)ことを確認する。
    これが本番障害の直接の修正対象。"""
    row = {"doc_id": "abc", "elyza_job_status": "cancelled"}
    remote_data = {"elyza_job_status": "pending"}
    payload = _build_push_payload(row, remote_data=remote_data)
    assert payload["elyza_job_status"] == "cancelled"


def test_worker_progress_still_protected_from_stale_local_overwrite():
    """ワーカーが既にclaimして"processing"/"completed"等へ進めた後は、
    Cloud Run側の陳腐化したローカル値("pending"等)で上書きされないことを
    (instructions/282の既存保護)引き続き確認する。"""
    for remote_status in ("processing", "completed", "dead_letter"):
        row = {"doc_id": "abc", "elyza_job_status": "pending"}
        remote_data = {"elyza_job_status": remote_status}
        payload = _build_push_payload(row, remote_data=remote_data)
        assert "elyza_job_status" not in payload, (
            f"remote={remote_status} のとき保護されるべきだが除外されなかった"
        )


def test_locked_at_and_retry_count_always_protected_when_remote_has_value():
    """Cloud Runが一切書かないelyza_job_locked_at/elyza_job_retry_countは、
    リモートに値がありさえすれば常に保護される(挙動不変)。"""
    row = {
        "doc_id": "abc",
        "elyza_job_locked_at": "2026-01-01T00:00:00+00:00",
        "elyza_job_retry_count": 0,
    }
    remote_data = {
        "elyza_job_locked_at": "2026-06-01T00:00:00+00:00",
        "elyza_job_retry_count": 2,
    }
    payload = _build_push_payload(row, remote_data=remote_data)
    assert "elyza_job_locked_at" not in payload
    assert "elyza_job_retry_count" not in payload


def test_non_worker_owned_fields_unaffected_by_remote_data():
    row = {"doc_id": "abc", "odai": "テスト", "status": "gemini_generated"}
    remote_data = {"elyza_job_status": "processing", "odai": "古いお題"}
    payload = _build_push_payload(row, remote_data=remote_data)
    assert payload["odai"] == "テスト"
    assert payload["status"] == "gemini_generated"
