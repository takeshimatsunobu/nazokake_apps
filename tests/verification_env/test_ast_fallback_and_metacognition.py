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


# --- AST脆弱性の克服: 対象ファイル自体の構文エラーに対するString-basedフォールバック ---


def test_ast_modifier_falls_back_to_string_replace_on_target_syntax_error():
    """対象ファイル自体が構文エラーを含みlibcstでパースできない場合(既存の
    syntax_error Fixtureそのもの)でも、apply_modification()がクラッシュ/エラー
    終了するのではなく、String-basedフォールバックで実際に修正を適用し、
    postfixテストが通る状態まで到達できることを確認する。
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

    assert not result.startswith("Error:"), f"フォールバックが失敗した: {result}"
    assert "Fallback" in result

    fixed_source = target.read_text(encoding="utf-8")
    namespace: dict = {}
    exec(compile(fixed_source, str(target), "exec"), namespace)  # noqa: S102
    assert namespace["shout"]("hello") == "HELLO!"


def test_ast_modifier_fallback_refuses_to_write_when_target_name_not_found():
    """String-basedフォールバックが、target_nameの定義位置すら特定できない場合は
    (安全側に倒して)元ファイルを一切変更せず、Errorを返すことを確認する。
    """
    tmpdir = tempfile.mkdtemp()
    target = Path(tmpdir) / "buggy.py"
    shutil.copyfile(SYNTAX_ERROR_FIXTURE_DIR / "buggy.py", target)
    original_broken_source = target.read_text(encoding="utf-8")

    result = ast_modifier.apply_modification(
        {
            "file_path": str(target),
            "target_name": "this_function_does_not_exist",
            "new_code": "def this_function_does_not_exist():\n    pass\n",
        }
    )

    assert result.startswith("Error:")
    assert target.read_text(encoding="utf-8") == original_broken_source


def test_ast_modifier_fallback_refuses_to_write_when_still_broken():
    """String-basedフォールバックを適用した後の全文が、それでもPython標準の
    ast.parseで構文エラーになる場合は、書き込みを行わずErrorを返すことを確認する
    (フォールバック自体が二重に失敗した場合の安全側フェイル)。
    """
    tmpdir = tempfile.mkdtemp()
    target = Path(tmpdir) / "buggy.py"
    shutil.copyfile(SYNTAX_ERROR_FIXTURE_DIR / "buggy.py", target)
    original_broken_source = target.read_text(encoding="utf-8")

    result = ast_modifier._apply_string_fallback(
        target,
        original_broken_source,
        "shout",
        'def shout(word):\n    return word.upper(\n',  # 括弧が閉じておらず依然壊れている
        RuntimeError("simulated original parse failure"),
    )

    assert result.startswith("Error:")
    assert target.read_text(encoding="utf-8") == original_broken_source
