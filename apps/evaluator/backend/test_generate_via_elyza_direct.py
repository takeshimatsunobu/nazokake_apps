"""test_generate_via_elyza_direct.py
=====================================
Push型アーキテクチャ(2026-08-18)移行: services/generation.py::
generate_via_elyza_direct() の単体テスト。Cloud RunからCloudflare Tunnel
経由で自宅PCのOllamaへ直接POSTする関数そのものを、Firestore/Ollama実サービス
へ接続せず検証する(httpx呼び出しをモック)。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_BACKEND_ROOT = Path(__file__).resolve().parent
_SHARED_CORE_ROOT = _PROJECT_ROOT / "packages" / "shared_core"
for _p in (_PROJECT_ROOT, _BACKEND_ROOT, _SHARED_CORE_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import services.generation as generation_module  # noqa: E402
from services.generation import ElyzaDirectUnavailable, generate_via_elyza_direct  # noqa: E402


def _valid_elyza_json() -> str:
    return (
        '{"associations": ["a"], "kakekotoba": ["b"], "shared_essence": "c", '
        '"surprise_check": "d", "toku": "解き", "kokoro": "こころ", '
        '"persona_comment": "コメント"}'
    )


@pytest.mark.anyio
async def test_raises_unavailable_when_endpoint_not_configured(monkeypatch):
    """LOCAL_ELYZA_ENDPOINT未設定なら、Ollamaへ一切アクセスせず即座に
    ElyzaDirectUnavailable(reason="elyza_endpoint_not_configured")を送出する。"""
    monkeypatch.delenv("LOCAL_ELYZA_ENDPOINT", raising=False)
    with patch.object(generation_module, "_elyza_direct_call_sync") as mock_call:
        with pytest.raises(ElyzaDirectUnavailable) as exc_info:
            await generate_via_elyza_direct("お題")
    mock_call.assert_not_called()
    assert exc_info.value.reason == "elyza_endpoint_not_configured"


@pytest.mark.anyio
async def test_success_returns_finalized_result(monkeypatch):
    """自宅PCから正常応答があれば、_finalize()済みの辞書(hint/toku/kokoro等)を返す。"""
    monkeypatch.setenv("LOCAL_ELYZA_ENDPOINT", "https://example.trycloudflare.com")
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "choices": [{"message": {"content": _valid_elyza_json()}}]
    }
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.post.return_value = mock_response

    with (
        patch.object(generation_module.httpx, "Client", return_value=mock_client),
        patch.object(
            generation_module,
            "_build_gen_prompts",
            new=_async_return(("sys", "user", 0.8)),
        ),
        patch.object(generation_module, "_log_generation_cost", new=_async_noop()),
    ):
        result = await generate_via_elyza_direct("お題")

    assert result["toku"] == "解き"
    assert result["kokoro"] == "こころ"
    # POST先がLOCAL_ELYZA_ENDPOINTを基点に組み立てられていること。
    called_url = mock_client.post.call_args[0][0]
    assert called_url == "https://example.trycloudflare.com/v1/chat/completions"


@pytest.mark.anyio
async def test_connect_error_raises_unavailable_with_home_pc_unreachable_reason(monkeypatch):
    """自宅PC未起動相当(httpx.ConnectError)は、Firestore往復無しで即座に
    ElyzaDirectUnavailable(reason="home_pc_unreachable")へ正規化される。"""
    monkeypatch.setenv("LOCAL_ELYZA_ENDPOINT", "https://example.trycloudflare.com")

    def _raise_connect_error(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    with (
        patch.object(generation_module, "_elyza_direct_call_sync", side_effect=_raise_connect_error),
        patch.object(
            generation_module,
            "_build_gen_prompts",
            new=_async_return(("sys", "user", 0.8)),
        ),
        patch.object(generation_module, "_log_generation_cost", new=_async_noop()),
    ):
        with pytest.raises(ElyzaDirectUnavailable) as exc_info:
            await generate_via_elyza_direct("お題")

    assert exc_info.value.reason == "home_pc_unreachable"


@pytest.mark.anyio
async def test_read_timeout_raises_unavailable_with_timeout_reason(monkeypatch):
    """推論が遅い場合(httpx.ReadTimeout)も、ElyzaDirectUnavailable
    (reason="elyza_inference_timeout")へ正規化される。"""
    monkeypatch.setenv("LOCAL_ELYZA_ENDPOINT", "https://example.trycloudflare.com")

    def _raise_read_timeout(*args, **kwargs):
        raise httpx.ReadTimeout("timed out")

    with (
        patch.object(generation_module, "_elyza_direct_call_sync", side_effect=_raise_read_timeout),
        patch.object(
            generation_module,
            "_build_gen_prompts",
            new=_async_return(("sys", "user", 0.8)),
        ),
        patch.object(generation_module, "_log_generation_cost", new=_async_noop()),
    ):
        with pytest.raises(ElyzaDirectUnavailable) as exc_info:
            await generate_via_elyza_direct("お題")

    assert exc_info.value.reason == "elyza_inference_timeout"


@pytest.mark.anyio
async def test_schema_invalid_response_raises_value_error_not_unavailable(monkeypatch):
    """実機からの応答はあったがJSONスキーマが不正な場合は、ElyzaDirectUnavailable
    ではなくValueErrorを送出する(データ完全性: PC未起動と実際のELYZA失敗を
    区別し、Gemini代打への黙った差し替えをしない)。"""
    monkeypatch.setenv("LOCAL_ELYZA_ENDPOINT", "https://example.trycloudflare.com")

    with (
        patch.object(generation_module, "_elyza_direct_call_sync", return_value="{invalid json"),
        patch.object(
            generation_module,
            "_build_gen_prompts",
            new=_async_return(("sys", "user", 0.8)),
        ),
        patch.object(generation_module, "_log_generation_cost", new=_async_noop()),
    ):
        with pytest.raises(ValueError):
            await generate_via_elyza_direct("お題")


def _async_return(value):
    async def _inner(*args, **kwargs):
        return value

    return _inner


def _async_noop():
    async def _inner(*args, **kwargs):
        return None

    return _inner
