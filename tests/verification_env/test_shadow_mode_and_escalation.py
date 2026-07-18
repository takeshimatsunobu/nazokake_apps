"""
tests/verification_env/test_shadow_mode_and_escalation.py
=============================================================
シャドウモード運用の強制と異常系ベンチマークの追加(instructions/159)。

ファクト評価が「6次元ベンチマークのハッピーパス通過」だけを根拠に完全自律化(メイン
リポジトリへの自動マージ)へ移行することはゼロトラスト原則の違反であるとして差し戻された。
この差し戻しに対する3つの要件(Must Fix)を、それぞれ動的/静的な検証として実装する:

1. Qwen単独では解決不可能な難易度のFixture
   (tools/benchmark/fixtures/ambiguous_multi_defect/)が、単一の浅い修正では解決
   できない(=真に曖昧・複合的な欠陥である)ことを、モック無しで実際にそのFixtureの
   コードを実行して証明する。
2. CTOエスカレーション経路(tools/agent_graph.py)が、実際のgit操作によって
   「メインの作業ディレクトリ/ブランチを一切変更しない隔離ワークツリー」上でのみ
   動作し、自動マージではなくPRドラフト生成で安全に一時停止(Suspend)することを、
   実際のgit worktreeを作成して動的に証明する。加えて、git push/自動マージ的な
   操作がソースコード中に一切存在しないことを静的にも保証する(将来の退行を防ぐ
   回帰ガード)。
3. ベンチマーク通過という成功体験がai_knowledge_base.jsonへ実際にフィードバック
   されることを、モック無しで実際にファイルへ追記して証明する。
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from tools import agent_graph  # noqa: E402
from tools import knowledge_retriever as kr  # noqa: E402

FIXTURES_DIR = BASE_DIR / "tools" / "benchmark" / "fixtures"
AMBIGUOUS_FIXTURE_DIR = FIXTURES_DIR / "ambiguous_multi_defect"


# --- Step 1: 異常系ベンチマーク(Qwen単独では解決不可能な難易度のFixture) ---------


def test_ambiguous_fixture_has_required_files():
    """新規Fixtureが既存Fixture(logic_error等)と同一の5ファイル構成に従っていること。"""
    required = {"buggy.py", "error_log.txt", "stable.py", "test_sanity.py", "test_target.py"}
    actual = {p.name for p in AMBIGUOUS_FIXTURE_DIR.iterdir() if p.is_file()}
    assert required <= actual


def test_ambiguous_fixture_buggy_output_matches_recorded_error_log():
    """buggy.pyを実際に実行した結果が、error_log.txtに記録された失敗内容と一致する
    こと(Fixtureが将来のリファクタリングでドリフトしていないことのモック無し確認)。

    sys.path/sys.modulesを汚染しないよう、モジュール名"buggy"をグローバルに
    import/reloadするのではなく、ファイルパスから直接一意な名前でロードする。
    """
    spec = importlib.util.spec_from_file_location(
        "ambiguous_multi_defect_buggy", AMBIGUOUS_FIXTURE_DIR / "buggy.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    actual = module.rank_scores([10, 50, 30, 80], 20)

    error_log = (AMBIGUOUS_FIXTURE_DIR / "error_log.txt").read_text(encoding="utf-8").strip()
    assert repr(actual) in error_log


def test_ambiguous_fixture_requires_fixing_both_defects_at_once():
    """このFixtureが「単一の浅い修正では解決できない」複合的な欠陥であることを、
    2つの部分修正のそれぞれを個別に適用しても失敗し続けることで動的に証明する
    (=Qwenが一方の欠陥だけに気づいて自信満々に修正案を出しても、テストは
    通らない難易度であることの客観的な根拠)。
    """
    source = (AMBIGUOUS_FIXTURE_DIR / "buggy.py").read_text(encoding="utf-8")
    expected = [(3, 80), (1, 50), (2, 30)]

    only_fix_doubling = source.replace("scores[i] * 2", "scores[i]")
    only_fix_sort_order = source.replace(
        "sorted(ranked, key=lambda pair: pair[1])",
        "sorted(ranked, key=lambda pair: pair[1], reverse=True)",
    )
    fully_fixed = only_fix_doubling.replace(
        "sorted(ranked, key=lambda pair: pair[1])",
        "sorted(ranked, key=lambda pair: pair[1], reverse=True)",
    )

    def _run(code: str) -> list:
        namespace: dict = {}
        exec(code, namespace)  # noqa: S102 - テスト内でFixture断片を評価するだけ
        return namespace["rank_scores"]([10, 50, 30, 80], 20)

    assert _run(only_fix_doubling) != expected
    assert _run(only_fix_sort_order) != expected
    assert _run(fully_fixed) == expected


# --- Step 2: PR駆動への制約(シャドウモードの強制) --------------------------------


def _current_branch(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def test_escalation_worktree_never_mutates_main_checkout():
    """tools/agent_graph.py の managed_git_worktree() が実際に隔離されたブランチ/
    ワークツリーを作成し、メインの作業ディレクトリのHEAD(チェックアウト状態)を
    一切変更しないこと、かつ処理後もワークツリーのディレクトリ自体は破棄されるが
    ブランチは(人間レビュー用に)残ることを、モック無しの実際のgit操作で確認する。

    テスト自身の後片付けとして、生成したブランチは末尾で削除する(本番の
    sandbox_verify_nodeは意図的にブランチを残すが、それはテストの責務ではない)。
    """
    if not (BASE_DIR / ".git").exists():
        pytest.skip(".gitが見つからないため、このリポジトリではgit worktree検証を"
                    "実行できません。")

    repo_root = BASE_DIR
    before_branch = _current_branch(repo_root)

    try:
        with agent_graph.managed_git_worktree(repo_root) as (worktree_path, branch_name):
            assert re.match(r"^escalation/issue-\d+-[0-9a-f]{32}$", branch_name)
            assert worktree_path.is_dir()
            # 隔離ワークツリー使用中も、メインの作業ディレクトリのHEADは不変であること。
            assert _current_branch(repo_root) == before_branch

        # with を抜けた後、ワークツリーの物理ディレクトリは破棄されている(使い捨て)。
        assert not worktree_path.exists()
        # メインの作業ディレクトリのHEADは、処理の前後を通じて一度も変化していない。
        assert _current_branch(repo_root) == before_branch

        # ブランチ自体は(人間レビューのために)削除されず残っている。
        branch_list = subprocess.run(
            ["git", "branch", "--list", branch_name],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
        )
        assert branch_name in branch_list.stdout
    finally:
        subprocess.run(
            ["git", "branch", "-D", branch_name],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )


def test_no_main_branch_write_or_automerge_capability_exists():
    """SSoT「6. Autonomous Repair & Escalation Loop」が要求する『隔離ブランチ+PR
    ドラフト生成による一時停止』フローが、将来の変更によって『git push』『メイン
    ブランチへの直接checkout』『自動マージ』のいずれかを獲得していないことを、
    ソースコードへの静的走査で保証する回帰ガード。

    ゼロトラスト原則(instructions/159)上、これらの操作パターンが1つでもエスカレー
    ション経路の実装ファイルに出現した場合は、レビュー無しでのメインブランチ書き込み
    経路が生まれた可能性が高いため、ここで即座にfailさせる。
    """
    source_files = [
        BASE_DIR / "tools" / "agent_graph.py",
        BASE_DIR / "tools" / "nazo_agent.py",
    ]
    forbidden_patterns = {
        "git push": re.compile(r"""["']git["']\s*,\s*["']push["']"""),
        "gh pr merge": re.compile(r"""["']gh["']\s*,\s*["']pr["']\s*,\s*["']merge["']"""),
        "--merge flag": re.compile(r"""["']--merge["']"""),
        "checkout main/master": re.compile(
            r"""["']checkout["']\s*,\s*["'](main|master)["']"""
        ),
        "push to origin main/master": re.compile(
            r"""["']origin["']\s*,\s*["'](main|master)["']"""
        ),
    }

    violations = []
    for path in source_files:
        text = path.read_text(encoding="utf-8")
        for label, pattern in forbidden_patterns.items():
            if pattern.search(text):
                violations.append(f"{path.name}: {label}")

    assert not violations, (
        f"メインブランチへの自動書き込み/自動マージの兆候を検出しました: {violations}"
    )


# --- Step 3: 経験再生アーキテクチャのループ完結の証明 -----------------------------


def test_record_experience_appends_and_persists_to_knowledge_base(tmp_path, monkeypatch, capsys):
    """tools.knowledge_retriever.record_experience()が、実際にai_knowledge_base.json
    (相当のファイル)へ新規エントリを追記・永続化し、稼働ログを標準出力へ出力する
    ことをモック無しで確認する(instructions/159: 経験再生アーキテクチャのループ完結)。
    """
    kb_path = tmp_path / "ai_knowledge_base.json"
    kb_path.write_text(
        json.dumps([{"id": "001", "summary": "既存の静的エントリ", "keywords": ["foo"],
                     "filepath": "tools/instructions/001_x.txt"}], ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(kr, "KNOWLEDGE_BASE_PATH", kb_path)

    new_entry = {
        "id": "runtime-escalation/issue-123-abc",
        "summary": "[CTOエスカレーション成功] 'rank_scores'の修正がベンチマークに通過した",
        "keywords": ["rank_scores", "AssertionError"],
        "filepath": "tools/audit_reports/pr_drafts/pr_draft_20260719_000000.md",
    }
    kr.record_experience(new_entry)

    persisted = json.loads(kb_path.read_text(encoding="utf-8"))
    assert len(persisted) == 2
    assert persisted[0]["id"] == "001"  # 既存エントリは破壊されず残っている
    assert persisted[1] == new_entry

    captured = capsys.readouterr()
    assert "Experience Replay" in captured.out
    assert "runtime-escalation/issue-123-abc" in captured.out

    # ループ完結の確認: 追記直後からretrieve_experiences()の検索対象になること。
    results = kr.retrieve_experiences("rank_scores AssertionError", top_k=3)
    assert any(r["id"] == new_entry["id"] for r in results)


def test_record_successful_escalation_experience_builds_correct_entry(monkeypatch):
    """_record_successful_escalation_experience()が、record_experience()へ渡す
    エントリ(id/summary/keywords/filepath)を正しく構築することを直接確認する。
    """
    captured: dict = {}
    monkeypatch.setattr(agent_graph, "record_experience", lambda entry: captured.update(entry))

    pr_draft_path = BASE_DIR / "tools" / "audit_reports" / "pr_drafts" / "pr_draft_test.md"
    agent_graph._record_successful_escalation_experience(
        branch_name="escalation/issue-123-abc",
        pr_draft_path=pr_draft_path,
        instruction={"target_name": "rank_scores", "triage_type": "bug_fix"},
        state={"file_path": "buggy.py", "diagnosis": "d", "error_log": "e"},
    )

    assert captured["id"] == "runtime-escalation/issue-123-abc"
    assert "rank_scores" in captured["summary"]
    assert captured["filepath"] == "tools/audit_reports/pr_drafts/pr_draft_test.md"
    assert isinstance(captured["keywords"], list)


def test_sandbox_verify_node_gates_experience_recording_on_benchmark_success():
    """sandbox_verify_node()内で_record_successful_escalation_experience()の呼び出しが
    'benchmark_summary.get("returncode") == 0' の直後にのみ存在することをソースコード
    上で確認する(instructions/159: 失敗した修正案を将来の検索対象として汚染しない、
    というゲーティングそのものの回帰ガード)。
    """
    source = inspect.getsource(agent_graph.sandbox_verify_node)
    match = re.search(
        r'if benchmark_summary\.get\("returncode"\) == 0:\s*\n'
        r"(?:\s*#.*\n)*"
        r"\s*_record_successful_escalation_experience\(",
        source,
    )
    assert match, "ベンチマーク通過判定の直後に経験記録が呼ばれていません"
