"""
tests/verification_env/test_ast_fallback_and_metacognition.py
=================================================================
instructions/164: AST脆弱性の克服とメタ認知の是正。

前回のベンチマークにおいて、Agentは「SyntaxErrorによりASTパースに失敗した結果
(success: null)」を無視し、ハルシネーション(すべて成功したという確証バイアス)を
引き起こした。この2つの根本原因(評価ロジックの緩さ・libcstの構造的な限界)それぞれに
対する回帰テストをここに固定する。
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from tools import ast_modifier  # noqa: E402
from tools.benchmark import run_benchmark as rb  # noqa: E402

SYNTAX_ERROR_FIXTURE_DIR = BASE_DIR / "tools" / "benchmark" / "fixtures" / "syntax_error"


# --- メタ認知の是正: success: null を確証バイアスなしに不合格としてカウントする ---


def test_compute_aggregate_counts_null_success_as_failure():
    """success: null(ASTパース失敗・推論のリトライ枯渇・例外中断等)が、成功率の
    分母から静かに除外されるのではなく、厳格に不合格(False)としてカウントされる
    ことを確認する(instructions/164のミッション文そのものの回帰テスト)。
    """
    results = [
        {"fixture": "logic_error", "success": True, "latency_ms": 100},
        {"fixture": "syntax_error", "success": None, "latency_ms": None},  # ASTパース失敗
        {"fixture": "type_error", "success": False, "latency_ms": 200},
    ]
    aggregate = rb._compute_aggregate(results)

    # 修正前の実装(`r["success"] is not None`で除外)であれば
    # success_rate = 1/2 = 0.5 (syntax_errorが分母からも除外される)になっていたはずだが、
    # 修正後は必ず3件全体を分母とし、success_rate = 1/3 になる。
    assert aggregate["success_rate"] == 1 / 3


def test_compute_aggregate_all_null_success_yields_zero_not_none():
    """全Fixtureがsuccess: nullで終わった場合、success_rateは(除外によって空リストと
    なり)Noneへフォールバックするのではなく、明確に0.0(全数不合格)になることを
    確認する。
    """
    results = [
        {"fixture": "a", "success": None, "latency_ms": None},
        {"fixture": "b", "success": None, "latency_ms": None},
    ]
    aggregate = rb._compute_aggregate(results)
    assert aggregate["success_rate"] == 0.0


# --- instructions/229: String-basedフォールバックの廃止とFail-Closed化 ---
#
# instructions/164が導入したString-basedフォールバック(_string_based_fallback_replace /
# _apply_string_fallback)は、対象ファイル自体の構文エラーによりlibcstでパースできない
# 場合に、正規表現ベースの行単位置換で修正を強行していた。この経路は通常経路が持つ
# 安全網(セマンティック差分検証・大量削除/挿入ヒューリスティック)のいずれも適用できず、
# 防弾ツールとしてのリスクの方が大きいと判断し、instructions/229で完全に削除した。
# 以下は、その削除後の意図した挙動(Fail-Closed: パースできないファイルへの書き込みは
# 一切行わず、必ずErrorを返す)を固定する回帰テスト。


def test_ast_modifier_fails_closed_on_target_syntax_error():
    """対象ファイル自体が構文エラーを含みlibcstでパースできない場合(既存の
    syntax_error Fixtureそのもの)、apply_modification()はフォールバックを試みず、
    即座にErrorを返し、ファイルの内容を一切変更しないことを確認する。
    """
    tmpdir = tempfile.mkdtemp()
    target = Path(tmpdir) / "buggy.py"
    shutil.copyfile(SYNTAX_ERROR_FIXTURE_DIR / "buggy.py", target)
    original_broken_source = target.read_text(encoding="utf-8")

    # 事前条件: このFixtureの現在の内容は、そもそもlibcstでパースできない
    # (このテスト自体がFixtureのドリフトを検知できるようにするため明示的に確認する)。
    import libcst as cst

    try:
        cst.parse_module(original_broken_source)
        raise AssertionError(
            "syntax_error fixtureのbuggy.pyがlibcstでパース可能になっている"
            "(Fixtureがドリフトした可能性があるため、このテストの前提が崩れている)"
        )
    except Exception:
        pass

    result = ast_modifier.apply_modification(
        {
            "file_path": str(target),
            "target_name": "shout",
            "new_code": 'def shout(word):\n    return word.upper() + "!"\n',
        }
    )

    assert result.startswith("Error:"), f"Fail-Closedにならなかった: {result}"
    assert target.read_text(encoding="utf-8") == original_broken_source

    # 削除済みのString-basedフォールバック関数がモジュールに残っていないことも
    # あわせて確認する(instructions/229の削除要求そのものの回帰テスト)。
    assert not hasattr(ast_modifier, "_string_based_fallback_replace")
    assert not hasattr(ast_modifier, "_apply_string_fallback")
