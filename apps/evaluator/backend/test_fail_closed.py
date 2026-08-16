
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

# Add project root to sys.path to allow imports from other packages
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_BACKEND_ROOT = Path(__file__).resolve().parent
_SHARED_CORE_ROOT = _PROJECT_ROOT / "packages" / "shared_core"
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))
if str(_SHARED_CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SHARED_CORE_ROOT))

# Now that the path is set, we can import the router
# The app in main.py is too complex, so we create a minimal app for this test
from api.deps import get_db
from api.routers import generate
from api.routers.persona_generate import _ResolvedPersona

# Create a minimal app and include only the router we need to test
app = FastAPI()
app.include_router(generate.router)

# 【本番Firestore汚染の根絶】従来はfirebase_admin.initialize_app(options={"projectId":
# "nazokakeapp-137e5"})でモジュール読み込み時に本番プロジェクトへ接続していたため、
# generate_ai()内のペルソナ解決(_resolve_persona_for_generation → get_personas(db))や
# get_status()のFirestore再Pull(_fetch_terminal_elyza_job)が実際に本番の
# nazokake_itemsコレクションへ読み書きしていた(エミュレータがこの開発機では
# Javaバージョン制約により起動できないため、tests/conftest.pyの自動フォールバックも
# 効かない)。get_db依存をMagicMockへ差し替えるだけでは、_resolve_persona_for_generation
# 内部のFirestoreクエリ(db.collection(...).stream()等)がMagicMockに対して呼ばれ
# 予測不能な挙動(TypeErrorや非JSON化可能な戻り値)になり得るため、Firestoreへ
# 実際に到達し得る関数はすべて名前レベルで明示的にモックする方針にする。
app.dependency_overrides[get_db] = lambda: MagicMock()


@pytest.mark.anyio
async def test_fail_closed_on_gemini_exception():
    """
    Tests that if process_gemini raises an unexpected exception,
    the API returns a generic error message and does not leak the exception details.

    本番Firestoreへは一切接続しない(get_db依存の差し替え、および
    _resolve_persona_for_generation/is_budget_exceeded/sync_once_safe/
    _fetch_terminal_elyza_jobの明示的モックにより、Firestoreへ到達し得る
    経路をすべて遮断している)。

    【generate_via_llmjp/run_evaluationもモックする理由】K_SERVICE未設定
    (ローカル開発相当)のためprocess_elyza()は直接Ollama呼び出し経路を通る。
    ローカルOllamaが起動していると実際に生成が成功し、その後のrun_evaluation()が
    services/evaluation.py内部でfirestore.client()を直接呼ぶ(ai_settings/
    persona_overrides取得目的、_ensure_firebase_app()を経由しないため本番
    Firestore未接続の状態ではValueErrorになる)。Gemini経路の失敗挙動を検証する
    のが本テストの目的でありELYZA経路の成否は無関係なため、Ollama/Firestoreの
    いずれにも依存しないよう両方ともモックする。
    【ELYZAを「成功だが意図的に遅延させる」形でモックする理由】process_gemini()と
    process_elyza()はasyncio.gatherで真に並行実行され、どちらも"message"
    フィールドへ書き込む(共有フィールド)。元のテスト(実際のOllamaを叩く経路)が
    安定してGeminiのエラーメッセージを観測できていたのは、明示的な同期のためでは
    なく、「Geminiの即時失敗によりstatus="error"が最初のポーリングで既に観測でき、
    ループがそこで抜ける」一方で「実機のELYZA生成には数秒〜数十秒かかり、
    最初のポーリング時点ではまだ"message"へ一切書き込んでいない」という実測latencyの
    偶然の組み合わせによるもの(このレース自体はテストが偶然マスクしていた
    既存のアプリ側の設計、根本修正はスコープ外)。Ollama/Firestoreへの依存を
    無くすために完全モック化すると、この暗黙のlatency差が消えて即座に競合が
    表面化するため、ELYZA側の完了をtest_fail_closed.py固有の短い遅延で
    意図的に再現し、テストの意図(Gemini経路の失敗時にstatus/messageが正しく
    設定され、内部エラー詳細が漏れないこと)を壊さずに元の安定した観測順序を
    保つ。
    """
    resolved_persona = _ResolvedPersona(
        settings={"name": "テストペルソナ", "prompt": "テスト用の人格説明文"},
        version_id="1__test0000000000",
        display_name="テストペルソナ",
        data_origin="builtin",
    )

    async def _delayed_elyza_success(*args, **kwargs):
        # Gemini側の即時失敗(status="error"書き込み)がテストの最初のポーリングで
        # 確実に観測されるよう、実機のOllama推論(実測数秒〜数十秒)を模した遅延を
        # 入れる。テストのポーリング間隔(1秒)より長くすることで、ELYZA側が
        # "message"へ書き込む前にテストのポーリングループがstatus="error"を
        # 検出して抜けることを保証する。
        await asyncio.sleep(3.0)
        return {"hint": "テストヒント", "toku": "テスト解き", "kokoro": "テストこころ"}

    with patch(
        "api.routers.generate.generate_via_gemini",
        side_effect=Exception("SREテスト用の致命的エラー"),
    ) as mock_gemini, \
         patch(
             "api.routers.generate.generate_via_llmjp",
             new=AsyncMock(side_effect=_delayed_elyza_success),
         ), \
         patch(
             "api.routers.generate.run_evaluation",
             new=AsyncMock(return_value={"scores": {}, "s_total": 4.0, "axis_comments": {}, "overall": "ok"}),
         ), \
         patch(
             "api.routers.generate._resolve_persona_for_generation",
             return_value=resolved_persona,
         ), \
         patch(
             "api.routers.generate.is_budget_exceeded",
             new=AsyncMock(return_value=False),
         ), \
         patch(
             "api.routers.generate.sync_once_safe",
             new=AsyncMock(),
         ), \
         patch(
             "api.routers.generate._fetch_terminal_elyza_job",
             new=AsyncMock(return_value=None),
         ):
        # Keep all background task operations, polling, and assertions inside the with patch context
        # so that the mock remains active until the asynchronous tasks complete.

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # 1. Call /generate to start the background task inside the patch context
            response = await client.post("/generate", json={"odai": "テストのお題"})
            assert response.status_code == 200
            data = response.json()
            task_id = data.get("task_id")
            assert task_id is not None

            # 2. Poll the /status endpoint until a terminal state is reached, also inside the patch context
            final_status = None
            message = ""
            for _ in range(10):  # Poll for a max of 10 seconds
                response = await client.get(f"/status/{task_id}")
                if response.status_code == 200:
                    data = response.json()
                    final_status = data.get("status")
                    message = data.get("message")
                    if final_status in ["all_completed", "error"]:
                        break
                await asyncio.sleep(1)  # Yield control to the event loop to let the background task run

            # 3. Assert that the final state is 'error' and the message is generic
            assert final_status == "error"
            assert message == "システム内部で予期せぬエラーが発生しました"
            assert "SREテスト用の致命的エラー" not in message
            mock_gemini.assert_called_once()

if __name__ == "__main__":
    import pytest
    pytest.main([__file__])
