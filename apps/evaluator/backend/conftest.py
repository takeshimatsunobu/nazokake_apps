"""conftest.py
===============
pytest実行時、本番Firestore(nazokakeapp-137e5)を誤って汚さないよう、
FIRESTORE_EMULATOR_HOSTを自動設定する(未設定時のみ、既存の値があれば尊重する)。
tests/conftest.pyと同じ方針(リポジトリ横断pytestとこのアプリ単体pytestの
両方から実行されるケースをカバーする)。

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
