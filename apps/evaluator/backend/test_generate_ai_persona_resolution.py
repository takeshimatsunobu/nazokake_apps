"""test_generate_ai_persona_resolution.py
===========================================
改修要件(案A): メイン画面(apps/evaluator/frontend/public/index.html)から
マイペルソナ/みんなのペルソナを選んで生成できるようにする、POST /api/generate
(apps/evaluator/backend/api/routers/generate.py::generate_ai)のペルソナ解決・
DB記録の単体テスト。

generate_ai()がnarrator_personas(マイペルソナ/みんなのペルソナ)を正しく解決し、
Gemini/ELYZA両方へ渡す合成済みプロンプト文字列・narrator_persona_id等のDB
メタデータを正しく組み立てて11軸評価パイプライン(progressive_generate)へ
引き渡すことを検証する。Firestore/Gemini実サービスへは接続しない
(unittest.mock.patchで代替)。
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from api.deps import handle_exceptions
from api.routers import generate as generate_router
from api.routers.persona_generate import _ResolvedPersona
from models.schemas import GenerateRequest
from nazokake_core import narrator_personas


@pytest.mark.anyio
async def test_generate_ai_resolves_custom_persona_and_dispatches_with_composed_prompt():
    """テストケース1(カスタムペルソナ生成): カスタムUUIDのpersona_idを渡した際、
    narrator_personasから解決された設定(tone/first_person込み)がGemini/ELYZA
    両方に渡すプロンプト文字列へ合成され、DB書き込みのnarrator_persona_id等が
    正しく"custom"として記録され、progressive_generate(11軸評価パイプライン)へ
    そのまま引き渡されること。"""
    db = MagicMock()
    resolved = _ResolvedPersona(
        settings={
            "display_name": "テストペルソナ",
            "prompt": "あなたは博識な老賢者です。",
            "first_person": "わし",
            "speech_style": "語尾に「じゃ」を付ける",
            "tone": "warm",
            "favorite_topics": ["歴史"],
            "taboo": [],
            "thinking_level": "medium",
        },
        version_id="custom-uuid-1__deadbeef12345678",
        display_name="テストペルソナ",
        data_origin="custom",
    )

    upserts: list[dict] = []

    async def fake_upsert(payload):
        upserts.append(payload)

    dispatched_args: dict = {}

    async def fake_guarded_progressive(*args, **kwargs):
        dispatched_args["args"] = args

    with patch("api.routers.generate._resolve_persona_for_generation", return_value=resolved), \
         patch("api.routers.generate.async_upsert_item", side_effect=fake_upsert), \
         patch("api.routers.generate.sync_once_safe", new=AsyncMock()), \
         patch("api.routers.generate._guarded_progressive", side_effect=fake_guarded_progressive):
        req = GenerateRequest(odai="お題", persona_id="custom-uuid-1", temperature=0.6)
        result = await generate_router.generate_ai(req, db=db)
        # generate_ai()はasyncio.create_task()で背景タスクを起動するだけで待たない
        # (HTTPをブロックしないための既存設計)ため、イベントループへ一度制御を
        # 譲ってタスクが実行されるのを待つ。
        await asyncio.sleep(0)

    assert result["status"] == "processing"
    assert upserts, "DBへの初回書き込みが行われていない"
    first_write = upserts[0]
    assert first_write["narrator_persona_id"] == "custom-uuid-1"
    assert first_write["narrator_persona_version_id"] == "custom-uuid-1__deadbeef12345678"
    assert first_write["narrator_persona_name"] == "テストペルソナ"
    assert first_write["data_origin"] == "custom"

    # ELYZAジョブスナップショット(persona列)にも合成済みプロンプトが入っていること
    # (ワーカーはFirestoreを引き直さずこのスナップショットをそのまま使うため、
    # ELYZA側もマイペルソナの口調設定を反映できる)。
    composed_prompt = first_write["persona"]["persona_prompt"]
    assert "あなたは博識な老賢者です。" in composed_prompt
    assert "一人称: わし" in composed_prompt
    assert "全体の雰囲気: warm" in composed_prompt

    # progressive_generate(既存の11軸評価・ELYZA8秒フォールバックのパイプライン)
    # へ合成済みプロンプトとnarrator_persona_idがそのまま引き渡されていること
    # (既存シグネチャ: db, doc_id, odai, pair_id, persona_prompt, temperature,
    # narrator_persona_id)。
    passed_args = dispatched_args["args"]
    assert passed_args[4] == composed_prompt
    assert passed_args[6] == "custom-uuid-1"


@pytest.mark.anyio
async def test_generate_ai_builtin_persona_prompt_is_unchanged():
    """回帰確認: ビルトイン(name/promptの2キーのみ)は_compose_persona_prompt()を
    経由しても既存の生成挙動を一切変えない(prompt原文がそのまま使われる)こと。"""
    db = MagicMock()
    resolved = _ResolvedPersona(
        settings={"name": "昭和生まれの天才漫才師", "prompt": "あなたは昭和生まれの天才漫才師です。"},
        version_id="1__abc123",
        display_name="昭和生まれの天才漫才師",
        data_origin="builtin",
    )

    upserts: list[dict] = []

    async def fake_upsert(payload):
        upserts.append(payload)

    with patch("api.routers.generate._resolve_persona_for_generation", return_value=resolved), \
         patch("api.routers.generate.async_upsert_item", side_effect=fake_upsert), \
         patch("api.routers.generate.sync_once_safe", new=AsyncMock()), \
         patch("api.routers.generate._guarded_progressive", new=AsyncMock()):
        req = GenerateRequest(odai="お題", persona_id=1, temperature=0.6)
        await generate_router.generate_ai(req, db=db)

    first_write = upserts[0]
    assert first_write["data_origin"] == "builtin"
    assert first_write["narrator_persona_id"] == "1"
    assert first_write["persona"]["persona_prompt"] == "あなたは昭和生まれの天才漫才師です。"


@pytest.mark.anyio
async def test_generate_ai_increments_usage_count_for_custom_persona():
    """改修要件(利用回数インクリメント配線): data_origin=="custom"の場合、
    narrator_personas.increment_usage_count(db, narrator_persona_id)が
    呼ばれること(persona_generate.py::generate_routed()と同一の加算パターン)。
    /api/generateは非同期(バックグラウンド生成)モデルのため、Gemini/ELYZAの
    実際の成否を待たずgenerate_ai()の同期部分で加算する。"""
    db = MagicMock()
    resolved = _ResolvedPersona(
        settings={"display_name": "テストペルソナ", "prompt": "あなたは博識な老賢者です。"},
        version_id="custom-uuid-1__deadbeef12345678",
        display_name="テストペルソナ",
        data_origin="custom",
    )

    with patch("api.routers.generate._resolve_persona_for_generation", return_value=resolved), \
         patch("api.routers.generate.async_upsert_item", new=AsyncMock()), \
         patch("api.routers.generate.sync_once_safe", new=AsyncMock()), \
         patch("api.routers.generate._guarded_progressive", new=AsyncMock()), \
         patch("api.routers.generate.narrator_personas.increment_usage_count") as mock_incr:
        req = GenerateRequest(odai="お題", persona_id="custom-uuid-1", temperature=0.6)
        await generate_router.generate_ai(req, db=db)

    mock_incr.assert_called_once_with(db, "custom-uuid-1")


@pytest.mark.anyio
async def test_generate_ai_increment_usage_count_runs_via_asyncio_to_thread():
    """ディープ監査#2の回帰確認: increment_usage_count(同期・ブロッキングI/O)が
    asyncio.to_threadでラップされ、イベントループを直接塞がない経路で呼ばれる
    こと。asyncio.to_thread自体をモックし、(関数, 位置引数...)の形で正しく
    呼ばれたことを検証する。"""
    db = MagicMock()
    resolved = _ResolvedPersona(
        settings={"display_name": "テストペルソナ", "prompt": "あなたは博識な老賢者です。"},
        version_id="custom-uuid-1__deadbeef12345678",
        display_name="テストペルソナ",
        data_origin="custom",
    )

    with patch("api.routers.generate._resolve_persona_for_generation", return_value=resolved), \
         patch("api.routers.generate.async_upsert_item", new=AsyncMock()), \
         patch("api.routers.generate.sync_once_safe", new=AsyncMock()), \
         patch("api.routers.generate._guarded_progressive", new=AsyncMock()), \
         patch("api.routers.generate.narrator_personas.increment_usage_count") as mock_incr, \
         patch("api.routers.generate.asyncio.to_thread", new=AsyncMock()) as mock_to_thread:
        req = GenerateRequest(odai="お題", persona_id="custom-uuid-1", temperature=0.6)
        await generate_router.generate_ai(req, db=db)

    mock_to_thread.assert_awaited_once_with(mock_incr, db, "custom-uuid-1")
    # asyncio.to_thread自体をモックしたため、increment_usage_countの生呼び出しは
    # 発生していない(呼び出しがasyncio.to_thread経由に一本化されていることの確認)。
    mock_incr.assert_not_called()


@pytest.mark.anyio
async def test_generate_ai_does_not_increment_usage_count_for_builtin_persona():
    """回帰確認: ビルトイン(data_origin=="builtin")では加算しないこと
    (みんなの人気ペルソナランキングはカスタムペルソナのみが対象のため)。"""
    db = MagicMock()
    resolved = _ResolvedPersona(
        settings={"name": "昭和生まれの天才漫才師", "prompt": "あなたは昭和生まれの天才漫才師です。"},
        version_id="1__abc123",
        display_name="昭和生まれの天才漫才師",
        data_origin="builtin",
    )

    with patch("api.routers.generate._resolve_persona_for_generation", return_value=resolved), \
         patch("api.routers.generate.async_upsert_item", new=AsyncMock()), \
         patch("api.routers.generate.sync_once_safe", new=AsyncMock()), \
         patch("api.routers.generate._guarded_progressive", new=AsyncMock()), \
         patch("api.routers.generate.narrator_personas.increment_usage_count") as mock_incr:
        req = GenerateRequest(odai="お題", persona_id=1, temperature=0.6)
        await generate_router.generate_ai(req, db=db)

    mock_incr.assert_not_called()


@pytest.mark.anyio
async def test_generate_ai_returns_404_for_unknown_persona_id():
    """テストケース2(不正IDフォールバック/エラーハンドリング): 存在しない
    persona_idが渡された場合、黙示フォールバックせず404を返すこと(§7.3方針を
    /api/generateでも維持)。"""
    db = MagicMock()

    with patch(
        "api.routers.generate._resolve_persona_for_generation",
        side_effect=HTTPException(status_code=404, detail="不明なpersona_id: does-not-exist"),
    ):
        req = GenerateRequest(odai="お題", persona_id="does-not-exist", temperature=0.6)
        with pytest.raises(HTTPException) as exc_info:
            await generate_router.generate_ai(req, db=db)

    assert exc_info.value.status_code == 404


@pytest.mark.parametrize(
    "bad_persona_id",
    [
        "a/b/c",  # Firestoreドキュメントパス区切り文字
        "../secret",
        "foo bar",  # 空白
        "a" * 65,  # max_length=64超過
    ],
)
def test_generate_request_rejects_invalid_persona_id_characters(bad_persona_id):
    """ディープ監査#3の回帰確認: "/"等のFirestoreドキュメントパス区切り文字や
    許可されない文字種を含むpersona_idはPydanticバリデーションの時点(422相当)で
    拒否されること。"""
    with pytest.raises(ValidationError):
        GenerateRequest(odai="お題", persona_id=bad_persona_id)


def test_narrator_personas_get_persona_returns_none_on_firestore_failure():
    """ディープ監査#4の回帰確認: Firestore接続障害時、get_persona()は例外を
    伝播させずNoneへ縮退すること(ビルトイン解決経路get_personas()と同じ
    フェイルセーフ方針)。"""
    db = MagicMock()
    db.collection.return_value.document.return_value.get.side_effect = Exception("接続エラー")

    result = narrator_personas.get_persona(db, "some-id")

    assert result is None


def test_narrator_personas_get_persona_version_returns_none_on_firestore_failure():
    """get_persona_version()も同様にFirestore障害時はNoneへ縮退すること。"""
    db = MagicMock()
    db.collection.return_value.document.return_value.get.side_effect = Exception("接続エラー")

    result = narrator_personas.get_persona_version(db, "some-version-id")

    assert result is None


@pytest.mark.anyio
async def test_handle_exceptions_masks_generic_exception_message():
    """ディープ監査#4の回帰確認: handle_exceptions(非HTTPException)は生の例外
    メッセージ(内部情報を含み得る)をレスポンスへ含めず、固定の汎用文言のみを
    返すこと(async関数の場合)。"""

    @handle_exceptions
    async def _boom():
        raise RuntimeError("内部の接続文字列やスタック情報を含む機密情報")

    result = await _boom()

    assert result["status"] == "error"
    assert "内部の接続文字列やスタック情報を含む機密情報" not in result["message"]
    assert result["message"] == "Internal Server Error: An unexpected error occurred."


def test_handle_exceptions_masks_generic_exception_message_sync():
    """sync関数の場合はHTTPException(500)として送出されるが、detailは同様に
    固定の汎用文言のみであること。"""

    @handle_exceptions
    def _boom():
        raise RuntimeError("内部の接続文字列やスタック情報を含む機密情報")

    with pytest.raises(HTTPException) as exc_info:
        _boom()

    assert exc_info.value.status_code == 500
    assert "内部の接続文字列やスタック情報を含む機密情報" not in exc_info.value.detail
    assert exc_info.value.detail == "Internal Server Error: An unexpected error occurred."


def test_generate_request_accepts_int_and_normalizes_to_str():
    """persona_idはint(既存クライアント互換)・str(マイペルソナUUID)いずれも
    受理し、内部ではstrへ正規化されること。"""
    req_int = GenerateRequest(odai="お題", persona_id=3)
    assert req_int.persona_id == "3"
    assert isinstance(req_int.persona_id, str)

    req_str = GenerateRequest(odai="お題", persona_id="custom-uuid-xyz")
    assert req_str.persona_id == "custom-uuid-xyz"

    # デフォルト値も従来のint(1)相当のstr"1"を維持する(後方互換)。
    req_default = GenerateRequest(odai="お題")
    assert req_default.persona_id == "1"
