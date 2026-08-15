"""tests/conftest.py
=====================
pytest実行時、Firestoreエミュレータが実際に起動している場合のみ
FIRESTORE_EMULATOR_HOSTを自動設定する(未設定・到達不能時は本物のFirestoreへ
接続する既存動作を維持する)。詳細な経緯はapps/evaluator/backend/conftest.pyの
docstring参照(2026-08-16、無条件設定が原因でtest_fail_closed.pyが25分ハング
する回帰を実際に踏んだため、到達性チェックを追加した)。

エミュレータの起動: scripts/start_firestore_emulator.ps1
(`firebase emulators:start --only firestore`、既定ポート8080)
"""
from __future__ import annotations

import os
import socket

import pytest

_DEFAULT_FIRESTORE_EMULATOR_HOST = "localhost:8080"
_REACHABILITY_TIMEOUT_SEC = 0.5


def _emulator_reachable(host_port: str) -> bool:
    try:
        host, port_str = host_port.rsplit(":", 1)
        port = int(port_str)
    except (ValueError, IndexError):
        return False
    try:
        with socket.create_connection((host, port), timeout=_REACHABILITY_TIMEOUT_SEC):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session", autouse=True)
def _use_firestore_emulator():
    if "FIRESTORE_EMULATOR_HOST" not in os.environ and _emulator_reachable(
        _DEFAULT_FIRESTORE_EMULATOR_HOST
    ):
        os.environ["FIRESTORE_EMULATOR_HOST"] = _DEFAULT_FIRESTORE_EMULATOR_HOST
    yield
