"""test_elyza_fallback_and_popular_personas.py
=================================================
改修要件: ELYZA 8秒ACK判定・Gemini Flash自動フォールバック、および
「みんなの人気ペルソナ」API(GET /v1/personas/popular)の単体テスト。

apps/evaluator/backend/test_fail_closed.py と同じ配置規約。
Firestore/Gemini実サービスへは接続しない(unittest.mock.patch / MagicMockで代替)。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.routers import persona_generate
from api.routers.generate import _fallback_metadata, _wait_for_elyza_ack, progressive_generate
from api.routers.personas import list_popular_personas as popular_personas_endpoint
from models.persona_schemas import GenerateRoutedRequest, Step1Result
from nazokake_core import narrator_personas


# ------------------------------------------------------------
# ELYZA 8秒ACK判定
# ------------------------------------------------------------


@pytest.mark.anyio
async def test_wait_for_elyza_ack_true_when_status_leaves_pending():
    """1回目はpending(未ACK)、2回目でprocessingへ遷移した場合、Trueで返る。"""
    statuses = iter(["pending", "processing"])

    async def fake_fetch(doc_id):
        return next(statuses)

    with patch("api.routers.generate._fetch_elyza_job_status", side_effect=fake_fetch):
        acked = await _wait_for_elyza_ack("doc-1", timeout_sec=10.0, poll_interval_sec=0.01)
    assert acked is True


@pytest.mark.anyio
async def test_wait_for_elyza_ack_false_on_timeout():
    """タイムアウトまでずっとpendingのままなら、Falseで返る(ワーカーオフライン判定)。"""

    async def fake_fetch(doc_id):
        return "pending"

    with patch("api.routers.generate._fetch_elyza_job_status", side_effect=fake_fetch):
        acked = await _wait_for_elyza_ack("doc-2", timeout_sec=0.05, poll_interval_sec=0.02)
    assert acked is False


@pytest.mark.anyio
async def test_wait_for_elyza_ack_false_when_doc_not_found():
    """ドキュメントが見つからない(None)場合もpending同然として扱い、Falseで返る。"""

    async def fake_fetch(doc_id):
        return None

    with patch("api.routers.generate._fetch_elyza_job_status", side_effect=fake_fetch):
        acked = await _wait_for_elyza_ack("doc-3", timeout_sec=0.05, poll_interval_sec=0.02)
    assert acked is False


# ------------------------------------------------------------
# fallback_triggered / engine メタデータ
# ------------------------------------------------------------


def test_fallback_metadata_when_pinch_hitter():
    result = _fallback_metadata({
        "llmjp_is_pinch_hitter": True,
        "llmjp_model_id": "gemini-3.5-flash-lite",
        "llmjp_fallback_reason": "worker_ack_timeout",
    })
    assert result == {
        "fallback_triggered": True,
        "engine": "gemini-flash (fallback)",
        "fallback_reason": "worker_ack_timeout",
    }


def test_fallback_metadata_when_normal_elyza():
    result = _fallback_metadata({"llmjp_is_pinch_hitter": False, "llmjp_model_id": None})
    assert result == {"fallback_triggered": False, "engine": "elyza", "fallback_reason": None}


def test_fallback_metadata_when_field_missing():
    """旧データ(llmjp_is_pinch_hitterキー自体が無い)でも安全にFalse側へ倒れる。"""
    result = _fallback_metadata({})
    assert result == {"fallback_triggered": False, "engine": "elyza", "fallback_reason": None}


# ------------------------------------------------------------
# ELYZA 8秒ACK判定・Gemini Flash自動フォールバック: progressive_generate()結合テスト
#
# 【方針】process_elyza/process_elyza_pinch_hitterはprogressive_generate()内部の
# クロージャで直接importできないため、LLM呼び出し・DB書き込みをモックした上で
# progressive_generate()自体を実行し、async_upsert_item()への書き込み内容を
# 検証する(改修要件の3テストケースにそのまま対応させる)。
# ------------------------------------------------------------


def _gemini_result():
    return {"hint": "ヒント", "toku": "解き", "kokoro": "こころ"}


def _evaluation_result(s_total=4.0):
    return {"scores": {}, "s_total": s_total, "axis_comments": {}, "overall": "ok"}


@pytest.mark.anyio
async def test_case1_worker_acks_quickly_and_completes_no_fallback(monkeypatch):
    """テストケース1(正常系): ジョブが2秒でprocessing→completedになる場合、
    ELYZAの結果がそのまま返り、代打(pinch hitter)は一切発火しないこと。"""
    monkeypatch.setenv("K_SERVICE", "test-service")
    upserts: list[dict] = []

    async def fake_upsert(payload):
        upserts.append(payload)

    worker_result = {
        "elyza_job_status": "completed",
        "llmjp_status": "completed",
        "result_llmjp": {"toku": "本物のELYZA解き"},
        "nazokake_text_llmjp": "本物のELYZA本文",
        "scores_llmjp": {},
        "s_total_llmjp": 4.2,
        "overall_llmjp": "ok",
        "axis_comments_llmjp": {},
    }

    with patch("api.routers.generate.async_upsert_item", side_effect=fake_upsert), \
         patch("api.routers.generate.is_budget_exceeded", new=AsyncMock(return_value=False)), \
         patch("api.routers.generate.generate_via_gemini", new=AsyncMock(return_value=_gemini_result())), \
         patch("api.routers.generate.run_evaluation", new=AsyncMock(return_value=_evaluation_result())), \
         patch("api.routers.generate.async_record_evaluation_score", new=AsyncMock()), \
         patch("api.routers.generate._wait_for_elyza_ack", new=AsyncMock(return_value=True)) as mock_ack, \
         patch("api.routers.generate._wait_for_elyza_worker_or_none", new=AsyncMock(return_value=worker_result)), \
         patch("api.routers.generate.sync_once_safe", new=AsyncMock()):
        await progressive_generate(
            object(), "doc-case1", "お題", "dpo-1",
            persona_prompt="p", temperature=0.8, narrator_persona_id="1",
        )

    mock_ack.assert_awaited_once()
    # 代打(pinch hitter)関連のフィールドは一切書き込まれていない。
    assert not any(u.get("llmjp_is_pinch_hitter") for u in upserts)
    assert not any("llmjp_fallback_reason" in u for u in upserts)
    # 二重実行防止用のcancelled書き込みも発火していない(ワーカーが正常に稼働したため)。
    assert not any(u.get("elyza_job_status") == "cancelled" for u in upserts)
    # ワーカーの本物の結果がそのままローカルSQLiteへマージされている。
    assert any(
        u.get("llmjp_status") == "completed" and u.get("s_total_llmjp") == 4.2
        for u in upserts
    )


@pytest.mark.anyio
async def test_case2_worker_offline_triggers_gemini_flash_fallback(monkeypatch):
    """テストケース2(フォールバック系): ジョブが8秒間pendingのままの場合、
    Gemini Flashが呼ばれ、fallback_triggered:True・fallback_reason・engineが
    正しく記録されること。"""
    monkeypatch.setenv("K_SERVICE", "test-service")
    upserts: list[dict] = []

    async def fake_upsert(payload):
        upserts.append(payload)

    with patch("api.routers.generate.async_upsert_item", side_effect=fake_upsert), \
         patch("api.routers.generate.is_budget_exceeded", new=AsyncMock(return_value=False)), \
         patch("api.routers.generate.generate_via_gemini", new=AsyncMock(return_value=_gemini_result())), \
         patch("api.routers.generate.run_evaluation", new=AsyncMock(return_value=_evaluation_result())), \
         patch("api.routers.generate.async_record_evaluation_score", new=AsyncMock()), \
         patch("api.routers.generate._wait_for_elyza_ack", new=AsyncMock(return_value=False)) as mock_ack, \
         patch("api.routers.generate.sync_once_safe", new=AsyncMock()):
        await progressive_generate(
            object(), "doc-case2", "お題", "dpo-2",
            persona_prompt="p", temperature=0.8, narrator_persona_id="1",
        )

    mock_ack.assert_awaited_once()
    pinch_writes = [u for u in upserts if u.get("llmjp_is_pinch_hitter")]
    assert pinch_writes, "代打(pinch hitter)の書き込みが発生していない"
    assert all(u.get("llmjp_fallback_reason") == "worker_ack_timeout" for u in pinch_writes)
    assert all(u.get("llmjp_model_id") == "gemini-3.5-flash-lite" for u in pinch_writes)
    # async_upsert_item()は実DBでは部分更新(既存行への差分マージ)のため、
    # ここでも全upsertを時系列にマージしてから最終状態を再現する
    # (2回目の"completed"書き込み単体にはllmjp_is_pinch_hitterが含まれないが、
    # 1回目の"generated"書き込みで既にTrueになっている実際のDB挙動と同じ)。
    merged: dict = {}
    for u in upserts:
        if u.get("doc_id") == "doc-case2":
            merged.update(u)
    assert merged.get("llmjp_status") == "completed"
    # GET /status/{doc_id}相当のメタデータ導出(_fallback_metadata)も確認する。
    meta = _fallback_metadata(merged)
    assert meta == {
        "fallback_triggered": True,
        "engine": "gemini-flash (fallback)",
        "fallback_reason": "worker_ack_timeout",
    }


@pytest.mark.anyio
async def test_case3_fallback_cancels_original_job_to_prevent_double_execution(monkeypatch):
    """テストケース3(二重実行防止): フォールバック発火時、元のELYZAジョブの
    elyza_job_statusが"cancelled"へ更新されること(後から自宅PCが起動しても
    ワーカーが二重推論しないようにするため)。"""
    monkeypatch.setenv("K_SERVICE", "test-service")
    upserts: list[dict] = []

    async def fake_upsert(payload):
        upserts.append(payload)

    with patch("api.routers.generate.async_upsert_item", side_effect=fake_upsert), \
         patch("api.routers.generate.is_budget_exceeded", new=AsyncMock(return_value=False)), \
         patch("api.routers.generate.generate_via_gemini", new=AsyncMock(return_value=_gemini_result())), \
         patch("api.routers.generate.run_evaluation", new=AsyncMock(return_value=_evaluation_result())), \
         patch("api.routers.generate.async_record_evaluation_score", new=AsyncMock()), \
         patch("api.routers.generate._wait_for_elyza_ack", new=AsyncMock(return_value=False)), \
         patch("api.routers.generate.sync_once_safe", new=AsyncMock()) as mock_sync:
        await progressive_generate(
            object(), "doc-case3", "お題", "dpo-3",
            persona_prompt="p", temperature=0.8, narrator_persona_id="1",
        )

    cancel_writes = [u for u in upserts if u.get("elyza_job_status") == "cancelled"]
    assert len(cancel_writes) == 1
    assert cancel_writes[0]["doc_id"] == "doc-case3"
    # cancelled書き込みが代打より前に(Firestoreへの即時同期を伴って)発生していること。
    cancel_index = upserts.index(cancel_writes[0])
    pinch_index = next(i for i, u in enumerate(upserts) if u.get("llmjp_is_pinch_hitter"))
    assert cancel_index < pinch_index
    assert mock_sync.await_count >= 1


# ------------------------------------------------------------
# みんなの人気ペルソナ: narrator_personas側のロジック
# ------------------------------------------------------------


def test_case2_list_popular_personas_sorts_by_usage_desc_and_excludes_deleted_or_hidden():
    """テストケース2(削除済み除外): is_deleted相当(deleted_at)のペルソナ、
    および非表示(is_visible=False)のペルソナはランキングから除外され、残りは
    usage_count降順で返ること。"""
    db = MagicMock()
    docs_data = [
        {"persona_id": "a", "is_builtin": False, "usage_count": 3, "zabuton_count": 1},
        {"persona_id": "b", "is_builtin": False, "usage_count": 1, "zabuton_count": 10},
        {"persona_id": "c", "is_builtin": False, "usage_count": 0, "zabuton_count": 0},
        {"persona_id": "d", "is_builtin": False, "deleted_at": "2026-01-01T00:00:00Z", "usage_count": 99, "zabuton_count": 99},
        {"persona_id": "e", "is_builtin": False, "is_visible": False, "usage_count": 50, "zabuton_count": 50},
    ]

    def _to_dict_factory(data):
        m = MagicMock()
        m.to_dict.return_value = data
        return m

    query = MagicMock()
    query.where.return_value = query
    query.stream.return_value = [_to_dict_factory(d) for d in docs_data]
    db.collection.return_value = query

    result = narrator_personas.list_popular_personas(db, limit=20)
    ids = [p["persona_id"] for p in result]
    # d(削除済み)・e(非表示)は除外され、usage_count降順でa(3) > b(1) > c(0)。
    assert ids == ["a", "b", "c"]


def test_list_popular_personas_offset_and_limit_slice_the_ranked_list():
    db = MagicMock()
    docs_data = [
        {"persona_id": pid, "is_builtin": False, "usage_count": count, "zabuton_count": 0}
        for pid, count in [("a", 5), ("b", 4), ("c", 3), ("d", 2), ("e", 1)]
    ]

    def _to_dict_factory(data):
        m = MagicMock()
        m.to_dict.return_value = data
        return m

    query = MagicMock()
    query.where.return_value = query
    query.stream.return_value = [_to_dict_factory(d) for d in docs_data]
    db.collection.return_value = query

    result = narrator_personas.list_popular_personas(db, limit=2, offset=1)
    ids = [p["persona_id"] for p in result]
    assert ids == ["b", "c"]


def test_increment_usage_count_is_best_effort_on_failure():
    db = MagicMock()
    db.collection.return_value.document.return_value.update.side_effect = Exception("boom")
    # 例外を送出しないことのみを確認する(呼び出し元の生成レスポンスを道連れにしない)。
    narrator_personas.increment_usage_count(db, "some-id")
    narrator_personas.increment_zabuton_count(db, "some-id")


# ------------------------------------------------------------
# みんなの人気ペルソナ: GET /v1/personas/popular エンドポイント本体
# ------------------------------------------------------------


def _make_snapshot(exists: bool, data: dict | None = None) -> MagicMock:
    snap = MagicMock()
    snap.exists = exists
    snap.to_dict.return_value = data
    return snap


@pytest.mark.anyio
async def test_case1_list_popular_personas_endpoint_returns_settings_sorted_by_usage_desc():
    """テストケース1(人気一覧取得): 複数のカスタムペルソナが存在する状態で
    GET /v1/personas/popular相当のエンドポイント関数を呼び出し、
    usage_count降順で、かつsystem_prompt/tone/first_personがそれぞれの
    現行バージョンのsettingsから正しく展開されて返ること。"""
    persona_docs = {
        "p-popular": {
            "persona_id": "p-popular", "is_builtin": False, "usage_count": 10,
            "zabuton_count": 2, "display_name": "人気者", "owner_uid": "uid-1",
            "owner_display_name": "たろう", "current_version_id": "p-popular__v1",
            "created_at": "2026-08-01T00:00:00+00:00", "is_visible": True, "deleted_at": None,
        },
        "p-minor": {
            "persona_id": "p-minor", "is_builtin": False, "usage_count": 2,
            "zabuton_count": 0, "display_name": "地味な子", "owner_uid": "uid-2",
            "owner_display_name": None, "current_version_id": "p-minor__v1",
            "created_at": "2026-08-02T00:00:00+00:00", "is_visible": True, "deleted_at": None,
        },
    }
    version_docs = {
        "p-popular__v1": {"settings": {"prompt": "人気ペルソナのプロンプト", "tone": "energetic", "first_person": "俺"}},
        "p-minor__v1": {"settings": {"prompt": "地味なペルソナのプロンプト", "tone": "gentle", "first_person": "私"}},
    }

    query = MagicMock()
    query.where.return_value = query
    query.stream.return_value = [
        _make_snapshot(True, d) for d in [persona_docs["p-popular"], persona_docs["p-minor"]]
    ]

    def _collection(name):
        col = MagicMock()
        if name == "narrator_personas":
            col.where.return_value = query
            col.document.side_effect = lambda pid: MagicMock(get=MagicMock(return_value=_make_snapshot(True, persona_docs[pid])))
        elif name == "narrator_persona_versions":
            col.document.side_effect = lambda vid: MagicMock(get=MagicMock(return_value=_make_snapshot(True, version_docs[vid])))
        return col

    db = MagicMock()
    db.collection.side_effect = _collection

    response = await popular_personas_endpoint(limit=10, offset=0, db=db)

    assert [p.persona_id for p in response.personas] == ["p-popular", "p-minor"]
    top = response.personas[0]
    assert top.name == "人気者"
    assert top.system_prompt == "人気ペルソナのプロンプト"
    assert top.tone == "energetic"
    assert top.first_person == "俺"
    assert top.usage_count == 10
    assert top.author_name == "たろう"
    assert top.author_slug == "uid-1"
    assert top.created_at == "2026-08-01T00:00:00+00:00"


@pytest.mark.anyio
async def test_generate_routed_increments_usage_count_for_custom_persona_route_a():
    """テストケース3(利用回数カウントアップ): カスタムペルソナ指定でPOST /v1/generateが
    成功(ルートA)した場合、narrator_personas.increment_usage_countが対象の
    persona_idで1回だけ呼ばれること(=次にGET /v1/personas/popularを叩けば
    usage_countが1増えて見える経路)。"""
    db = MagicMock()
    resolved = persona_generate._ResolvedPersona(
        settings={"prompt": "p", "tone": "warm"},
        version_id="my-uuid-1__deadbeef",
        display_name="テストペルソナ",
        data_origin="custom",
    )
    step1 = Step1Result(
        is_valid_input=True,
        domain_category="daily_life",
        vocabulary_difficulty="standard",
        slang_level="none",
        wordplay_flexibility="medium",
        topic_scale="personal",
        is_seasonal=False,
    )

    with patch("api.routers.persona_generate.check_block_status", return_value=MagicMock(blocked=False)), \
         patch("api.routers.persona_generate._resolve_persona_for_generation", return_value=resolved), \
         patch("api.routers.persona_generate.get_cached_step1", return_value=step1), \
         patch("api.routers.persona_generate.generate_step2", new=AsyncMock(return_value=("A", "解き", "こころ", "本文", "model-x"))), \
         patch("api.routers.persona_generate.narrator_personas.increment_usage_count") as mock_incr:
        req = GenerateRoutedRequest(odai="お題", persona_id="my-uuid-1", client_uuid="u1")
        result = await persona_generate.generate_routed(req, db=db)

    assert result.route == "A"
    mock_incr.assert_called_once_with(db, "my-uuid-1")


@pytest.mark.anyio
async def test_generate_routed_does_not_increment_usage_count_for_route_b():
    """異常入力(ルートB)は「利用」として数えない(既存の設計方針、回帰確認)。"""
    db = MagicMock()
    resolved = persona_generate._ResolvedPersona(
        settings={"prompt": "p", "tone": "warm"},
        version_id="my-uuid-1__deadbeef",
        display_name="テストペルソナ",
        data_origin="custom",
    )
    step1 = Step1Result(
        is_valid_input=False,
        domain_category="general_unknown",
        vocabulary_difficulty="standard",
        slang_level="none",
        wordplay_flexibility="low",
        topic_scale="personal",
        is_seasonal=False,
    )

    with patch("api.routers.persona_generate.check_block_status", return_value=MagicMock(blocked=False)), \
         patch("api.routers.persona_generate._resolve_persona_for_generation", return_value=resolved), \
         patch("api.routers.persona_generate.get_cached_step1", return_value=step1), \
         patch("api.routers.persona_generate.generate_step2", new=AsyncMock(return_value=("B", "解き", "こころ", "本文", "model-x"))), \
         patch("api.routers.persona_generate.narrator_personas.increment_usage_count") as mock_incr, \
         patch("api.routers.persona_generate.record_route_b"):
        req = GenerateRoutedRequest(odai="お題", persona_id="my-uuid-1", client_uuid="u1")
        result = await persona_generate.generate_routed(req, db=db)

    assert result.route == "B"
    mock_incr.assert_not_called()
