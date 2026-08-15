"""tests/conftest.py
=====================
pytest実行時、本番Firestore(nazokakeapp-137e5)を誤って汚さないよう、
FIRESTORE_EMULATOR_HOSTを自動設定する(未設定時のみ、既存の値があれば尊重する)。

firebase_admin.firestore.client()を含むGoogle Cloud Firestoreクライアント
ライブラリは、この環境変数が設定されている場合、本番資格情報を検証せず
自動的にそのホストへ接続する(公式SDK共通の規約)。実際にエミュレータが
起動していない状態でもこのfixture自体は失敗しない(接続はテストが実際に
Firestore操作を行った時点で初めて発生するため)。

エミュレータの起動: scripts/start_firestore_emulator.ps1
(`firebase emulators:start --only firestore`、既定ポート8080)
"""
from __future__ import annotations

import os

import pytest

_DEFAULT_FIRESTORE_EMULATOR_HOST = "localhost:8080"


@pytest.fixture(scope="session", autouse=True)
def _use_firestore_emulator():
    os.environ.setdefault("FIRESTORE_EMULATOR_HOST", _DEFAULT_FIRESTORE_EMULATOR_HOST)
    yield
