"""conftest.py
===============
pytest実行時、Firestoreエミュレータが実際に起動している場合のみ
FIRESTORE_EMULATOR_HOSTを自動設定する(本番Firestoreを誤って汚さないための
仕組み)。tests/conftest.pyと同じ方針(リポジトリ横断pytestとこのアプリ単体
pytestの両方から実行されるケースをカバーする)。

【2026-08-16: 到達性チェックを追加した理由】当初は無条件でFIRESTORE_EMULATOR_HOST
を設定していたが、エミュレータが実際には起動していない環境(この開発機はJava
バージョン制約でfirebase emulators:startが起動できない、scripts/
start_firestore_emulator.ps1のコメント参照)でtest_fail_closed.pyを実行すると、
firestore.client()が存在しないlocalhost:8080への接続を延々リトライし続け、
本来数秒で終わるテストが実行時間25分・失敗という深刻な回帰を起こすことが
判明した(全テストスイート結合実行での実測)。エミュレータへの到達性を
先に軽量TCP接続で確認し、到達できない場合は環境変数を設定しない
(=既存の「本物のFirestoreへ接続する」フォールバック動作を維持する)ことで、
「エミュレータがあれば使う、無ければ壊れない」を両立する。

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
