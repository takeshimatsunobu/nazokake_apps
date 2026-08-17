"""採点中スピナー固着調査(2026-08-18)の回帰テスト。

services/evaluation.py::run_evaluation() のGemini呼び出しには従来タイムアウトが
無く、services/generation.py(ELYZA/Ollama側、httpx.Timeout(120.0))と非対称
だった。Gemini API側が応答を返さない場合、process_gemini()がasyncio.gather内で
無期限に停止し得る(ELYZA側は独立コルーチンのため先に完了し、結果として
「ELYZAだけ描画されGemini側だけ採点中のまま」という見た目になり得る)ことへの
対処として、_EVAL_TIMEOUT_SEC(60秒)の明示的タイムアウトを追加した。

本テストは、Gemini呼び出しがハングしても_EVAL_TIMEOUT_SEC超過で確実に
例外(TimeoutError)が送出されることを検証する(呼び出し元process_gemini()の
既存except節がこれを捕捉しstatus="error"へ倒す設計は変更していない)。
"""

import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_BACKEND_ROOT = Path(__file__).resolve().parent
_SHARED_CORE_ROOT = _PROJECT_ROOT / "packages" / "shared_core"
for _p in (_PROJECT_ROOT, _BACKEND_ROOT, _SHARED_CORE_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import services.evaluation as evaluation_module  # noqa: E402


@pytest.mark.anyio
async def test_run_evaluation_raises_timeout_when_gemini_call_hangs():
    def _hang(*args, **kwargs):
        time.sleep(5)
        return MagicMock()

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = _hang

    with (
        patch.object(evaluation_module.genai, "Client", return_value=mock_client),
        patch.object(evaluation_module, "_EVAL_TIMEOUT_SEC", 0.05),
    ):
        start = asyncio.get_running_loop().time()
        with pytest.raises(asyncio.TimeoutError):
            await evaluation_module.run_evaluation("お題", "なぞかけ本文")
        elapsed = asyncio.get_running_loop().time() - start

    # タイムアウト値(0.05秒)近辺で確実に打ち切られること(ハング側の5秒を
    # 待たされていないこと)を確認する。
    assert elapsed < 3.0


@pytest.mark.anyio
async def test_run_evaluation_succeeds_within_timeout_when_gemini_responds_fast():
    mock_response = MagicMock()
    mock_response.text = (
        '{"scores": {"S_nat": 0.5, "S_tech": 0.5, "S_rhy": 0.5, "S_prosody": 0.5, '
        '"S_sur": 0.5, "S_emo": 0.5, "S_cultural": 0.5, "S_visual": 0.5, '
        '"S_sensory": 0.5, "S_cm": 0.5, "S_ontology": 0.5}, '
        '"axis_comments": {"S_nat": "ok", "S_tech": "ok", "S_rhy": "ok", '
        '"S_prosody": "ok", "S_sur": "ok", "S_emo": "ok", "S_cultural": "ok", '
        '"S_visual": "ok", "S_sensory": "ok", "S_cm": "ok", "S_ontology": "ok"}, '
        '"overall": "総評"}'
    )
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    with (
        patch.object(evaluation_module.genai, "Client", return_value=mock_client),
        patch.object(evaluation_module, "_EVAL_TIMEOUT_SEC", 5.0),
    ):
        result = await evaluation_module.run_evaluation("お題", "なぞかけ本文")

    assert result["s_total"] == 2.5
    assert result["overall"] == "総評"
