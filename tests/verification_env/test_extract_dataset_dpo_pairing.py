"""
tests/verification_env/test_extract_dataset_dpo_pairing.py
=============================================================
instructions/251: dpo_pair_idによる直接ペアリング(Gemini/ELYZA、または
バッチ工場の対応行)の回帰テスト。

human_evaluations/is_golden_dataによる既存の適格性ゲートはバイパスせず、
classify()通過済みのchosen/rejectedに対してのみdpo_pair_idベースの直接
ペアリングを試みる、という設計そのものを固定する。
"""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR / "tools") not in sys.path:
    sys.path.insert(0, str(BASE_DIR / "tools"))

from extract_dataset import Candidate, _pair_by_dpo_pair_id, build_dpo_pairs  # noqa: E402


def _candidate(**overrides) -> Candidate:
    base = dict(
        doc_id="doc-1",
        odai="サウナ",
        answer_text="answer",
        score=4.5,
        is_golden=False,
        trained_at=None,
        dpo_pair_id=None,
        source="unknown",
        engine_score=None,
    )
    base.update(overrides)
    # dict[str, Any]的な**展開のため、Pyrightはbase各キーの値を個別に検証できず
    # Candidateの各フィールド型との不一致を報告する(実際の値は各キーとも正しい型)。
    return Candidate(**base)  # pyright: ignore[reportArgumentType]


def test_same_dpo_pair_id_with_differing_engine_scores_forms_a_pair():
    """同一dpo_pair_id・engine_scoreが異なるGemini/ELYZA候補は、engine_scoreの
    高い方がchosen・低い方がrejectedとして直接ペアリングされる。
    """
    gemini = _candidate(
        doc_id="d1", answer_text="ゲミニ解答", dpo_pair_id="dpo-abc",
        source="gemini", engine_score=4.8,
    )
    elyza = _candidate(
        doc_id="d1", answer_text="エリザ解答", dpo_pair_id="dpo-abc",
        source="elyza", engine_score=3.2,
    )

    pairs, remaining_chosen, remaining_rejected = _pair_by_dpo_pair_id([gemini, elyza], [])

    assert pairs == [
        {"prompt": "サウナ", "chosen": "ゲミニ解答", "rejected": "エリザ解答"}
    ]
    assert remaining_chosen == []
    assert remaining_rejected == []


def test_equal_engine_scores_do_not_form_a_pair():
    """engine_scoreが同一(優劣不明)の場合、ノイズ注入を避けるためペアリングしない。
    両候補ともフォールバック(odaiベース)の対象として手元に残る。
    """
    gemini = _candidate(doc_id="d2", dpo_pair_id="dpo-xyz", source="gemini", engine_score=4.0)
    elyza = _candidate(doc_id="d2", dpo_pair_id="dpo-xyz", source="elyza", engine_score=4.0)

    pairs, remaining_chosen, _ = _pair_by_dpo_pair_id([gemini, elyza], [])

    assert pairs == []
    assert len(remaining_chosen) == 2


def test_missing_engine_score_does_not_form_a_pair():
    """片方のengine_scoreがNone(旧データ等)の場合もペアリングしない。"""
    gemini = _candidate(doc_id="d3", dpo_pair_id="dpo-legacy", source="gemini", engine_score=4.5)
    elyza = _candidate(doc_id="d3", dpo_pair_id="dpo-legacy", source="elyza", engine_score=None)

    pairs, remaining_chosen, _ = _pair_by_dpo_pair_id([gemini, elyza], [])

    assert pairs == []
    assert len(remaining_chosen) == 2


def test_candidates_without_dpo_pair_id_are_untouched():
    """dpo_pair_idが無い候補(旧データ等)は、このペアリングの対象外として
    そのまま残り、既存のodaiベースのフォールバックに委ねられる。
    """
    solo = _candidate(doc_id="d4", dpo_pair_id=None, source="gemini", engine_score=4.9)

    pairs, remaining_chosen, remaining_rejected = _pair_by_dpo_pair_id([solo], [])

    assert pairs == []
    assert remaining_chosen == [solo]
    assert remaining_rejected == []


def test_dpo_pair_id_group_with_more_than_two_members_is_skipped_safely():
    """1つのdpo_pair_idに3件以上の候補が紐付く想定外のデータは、安全側に倒して
    直接ペアリングをスキップし、既存のodaiベースのフォールバックに委ねる。
    """
    a = _candidate(doc_id="d5", dpo_pair_id="dpo-triple", source="gemini", engine_score=4.9)
    b = _candidate(doc_id="d6", dpo_pair_id="dpo-triple", source="elyza", engine_score=3.9)
    c = _candidate(doc_id="d7", dpo_pair_id="dpo-triple", source="elyza", engine_score=2.9)

    pairs, remaining_chosen, _ = _pair_by_dpo_pair_id([a, b, c], [])

    assert pairs == []
    assert len(remaining_chosen) == 3


def test_build_dpo_pairs_prefers_dpo_pair_id_then_falls_back_to_odai_grouping():
    """build_dpo_pairsはdpo_pair_idによる直接ペアを先に確定させ、そこで消費
    されなかった残りの候補にのみ既存のodaiベースのフォールバックを適用する。
    """
    gemini = _candidate(
        doc_id="d1", odai="サウナ", answer_text="ゲミニ解答", dpo_pair_id="dpo-abc",
        source="gemini", engine_score=4.8,
    )
    elyza = _candidate(
        doc_id="d1", odai="サウナ", answer_text="エリザ解答", dpo_pair_id="dpo-abc",
        source="elyza", engine_score=3.2,
    )
    # 別のお題の、dpo_pair_id無しの既存odaiベースの組(フォールバック対象)。
    other_chosen = _candidate(
        doc_id="d8", odai="猫", answer_text="良い解答", dpo_pair_id=None,
    )
    other_rejected = _candidate(
        doc_id="d9", odai="猫", answer_text="悪い解答", dpo_pair_id=None,
    )

    pairs = build_dpo_pairs([gemini, elyza, other_chosen], [other_rejected])

    assert {"prompt": "サウナ", "chosen": "ゲミニ解答", "rejected": "エリザ解答"} in pairs
    assert {"prompt": "猫", "chosen": "良い解答", "rejected": "悪い解答"} in pairs
    assert len(pairs) == 2
