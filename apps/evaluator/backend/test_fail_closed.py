
import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
import firebase_admin

# Initialize firebase app before other imports
if not firebase_admin._apps:
    firebase_admin.initialize_app(options={"projectId": "nazokakeapp-137e5"})


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
from apps.evaluator.backend.api.routers import generate

# Create a minimal app and include only the router we need to test
app = FastAPI()
app.include_router(generate.router)


@pytest.mark.anyio
async def test_fail_closed_on_gemini_exception():
    """
    Tests that if process_gemini raises an unexpected exception,
    the API returns a generic error message and does not leak the exception details.
    """
    with patch(
        "apps.evaluator.backend.api.routers.generate.generate_via_gemini",
        side_effect=Exception("SREテスト用の致命的エラー"),
    ) as mock_gemini:
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
