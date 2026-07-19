"""
tools/cleanup_git_resources.py
=================================
Nazo-Agentの自律エスカレーション(tools/agent_graph.py の managed_git_worktree)は、
隔離用の物理worktreeディレクトリ自体は使用直後に必ず破棄する(finallyブロック)ものの、
レビュー用に残す設計の escalation/* ブランチ自体は破棄しない。CTOエスカレーションが
無人稼働で走るたびにブランチが増え続けるため、放置するとローカルGitのメタデータ(refs)が
肥大化しストレージを圧迫する(instructions/175)。

【絶対基準: メインブランチへのマージ状態】経過時間による推測削除(例:「作成から7日
経過したら削除」)は、レビューが長引いているだけの正当なブランチを誤って破棄する
システム破壊の温床となるため禁止する。`git branch --merged <main/master>` が返す
「既にメインブランチへ取り込まれた」という決定論的な事実のみを削除の絶対基準とする。
未マージのブランチ(レビュー中・実験中を含む)はこのコードパスから一切操作しない
(git branch --merged自体がそもそも一覧に含めないため、保護は構造的に担保される)。

対象は escalation/*(instructions/124のCTOエスカレーション)および draft/*(過去に
tools/nazo_agent.pyが生成していた隔離ドラフトブランチの残存物)のプレフィックスに
合致するブランチのみ。main/master自身や開発者の作業ブランチ等はプレフィックスに
合致しないため対象外。

worktree自体はmanaged_git_worktreeのfinallyで既に破棄されている想定だが、プロセスが
SIGKILL等で強制終了した場合はfinallyが走らず`git worktree list`上の登録が残存し得る。
worktreeが紐づいたブランチは`git branch -d`が失敗するため、対象ブランチにworktreeが
紐づいている場合は必ず`git worktree remove --force`を先に実行してからブランチを削除する。

使い方:
    uv run python tools/cleanup_git_resources.py             # 実際に削除を実行
    uv run python tools/cleanup_git_resources.py --dry-run   # 削除対象の一覧表示のみ
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# 削除対象とみなすブランチ名のプレフィックス。これに合致しないブランチ
# (main/master、開発者の作業ブランチ等)は--mergedの結果に含まれていても一切操作しない。
TARGET_PREFIXES = ("escalation/", "draft/")


def _run_git(args: list[str], repo_root: Path) -> subprocess.CompletedProcess:
    """gitサブコマンドを実行し、CompletedProcessをそのまま返す(呼び出し元がreturncode/
    stderrを見て判断する。checkは付けず、呼び出し元に判断を委ねる)。
    """
    return subprocess.run(
        ["git", *args],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _resolve_main_branch(repo_root: Path) -> str:
    """main/masterのうち、実際にローカルに存在する方を返す(main優先)。

    削除基準そのものの土台となるブランチが存在しない場合、誤操作を避けて
    即座にRuntimeErrorを送出する(呼び出し元は何も削除せずに終了すべき)。
    """
    for candidate in ("main", "master"):
        result = _run_git(
            ["show-ref", "--verify", "--quiet", f"refs/heads/{candidate}"], repo_root
        )
        if result.returncode == 0:
            return candidate
    raise RuntimeError("main/masterブランチのいずれもローカルに見つかりませんでした。")


def _list_merged_target_branches(repo_root: Path, main_branch: str) -> list[str]:
    """`git branch --merged <main_branch>` の結果から、TARGET_PREFIXESに合致する
    ブランチ名のみを抽出する(main_branch自身、および接頭辞に合致しない他ブランチは
    構造的に除外される=未マージのブランチはそもそもこの一覧に現れない)。
    """
    result = _run_git(["branch", "--merged", main_branch], repo_root)
    if result.returncode != 0:
        raise RuntimeError(
            f"git branch --mergedの実行に失敗しました: {result.stderr.strip()}"
        )

    branches = []
    for line in result.stdout.splitlines():
        # `git branch`の出力は先頭2文字がインジケータ("* "=カレント、"+ "=他worktreeで
        # チェックアウト中、"  "=通常)のため、必ず先頭から剥がす。
        name = line[2:].strip() if len(line) > 2 else line.strip()
        if not name or name == main_branch:
            continue
        if name.startswith(TARGET_PREFIXES):
            branches.append(name)
    return branches


def _find_worktree_path_for_branch(repo_root: Path, branch_name: str) -> Path | None:
    """`git worktree list --porcelain`から、指定ブランチに紐づくworktreeの物理パスを
    探す。紐づくworktreeが見つからない場合はNone(通常のケース。managed_git_worktreeが
    worktree自体は使用直後に破棄済みのため、ここでヒットするのはSIGKILL等でfinallyが
    走らなかった異常系のみ)。
    """
    result = _run_git(["worktree", "list", "--porcelain"], repo_root)
    if result.returncode != 0:
        return None

    branch_ref = f"refs/heads/{branch_name}"
    current_path: str | None = None
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            current_path = line[len("worktree ") :].strip()
        elif line.startswith("branch ") and line[len("branch ") :].strip() == branch_ref:
            if current_path is not None:
                return Path(current_path)
    return None


def cleanup_merged_git_resources(repo_root: Path | None = None, *, dry_run: bool = False) -> dict:
    """メインブランチへマージ済みのescalation/*・draft/*ブランチ(および紐づくworktree、
    残存していれば)を安全に削除する(instructions/175)。

    未マージのブランチは_list_merged_target_branches自体がgit branch --mergedの結果
    にしか反応しないため、このコードパスから構造的に一切操作されない(保護対象)。
    dry_run=Trueの場合は削除対象を特定してログ表示するだけで、実際のgit worktree
    remove/git branch -dは実行しない。
    {"removed": [...], "worktrees_removed": [...], "errors": [...]}を返す。
    """
    root = repo_root or BASE_DIR
    result: dict = {"removed": [], "worktrees_removed": [], "errors": []}

    try:
        main_branch = _resolve_main_branch(root)
        merged_branches = _list_merged_target_branches(root, main_branch)
    except RuntimeError as e:
        result["errors"].append(str(e))
        return result

    for branch_name in merged_branches:
        worktree_path = _find_worktree_path_for_branch(root, branch_name)
        if worktree_path is not None:
            if dry_run:
                print(f"🧪 [dry-run] worktree削除予定: {worktree_path} (branch={branch_name})")
            else:
                wt_result = _run_git(
                    ["worktree", "remove", "--force", str(worktree_path)], root
                )
                if wt_result.returncode != 0:
                    result["errors"].append(
                        f"{branch_name}: git worktree removeに失敗しました: "
                        f"{wt_result.stderr.strip()}"
                    )
                    # worktreeが紐づいたままだとgit branch -dが必ず失敗するため、
                    # このブランチのブランチ削除は諦めて次のブランチへ進む
                    # (安全側に倒し、中途半端な状態(worktreeもブランチも残存)
                    # として次回サイクルの再試行に委ねる)。
                    continue
                result["worktrees_removed"].append(str(worktree_path))
                print(
                    f"🗑️  [cleanup] worktreeを削除しました: {worktree_path} "
                    f"(branch={branch_name})"
                )

        if dry_run:
            print(f"🧪 [dry-run] ブランチ削除予定: {branch_name}")
            continue

        branch_result = _run_git(["branch", "-d", branch_name], root)
        if branch_result.returncode != 0:
            result["errors"].append(
                f"{branch_name}: git branch -dに失敗しました: {branch_result.stderr.strip()}"
            )
            continue
        result["removed"].append(branch_name)
        print(f"🗑️  [cleanup] マージ済みブランチを削除しました: {branch_name}")

    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="メインブランチへマージ済みのescalation/*・draft/*ブランチ/worktreeを削除する"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="実際に削除せず、削除対象の一覧表示のみ行う"
    )
    args = parser.parse_args()

    result = cleanup_merged_git_resources(dry_run=args.dry_run)

    for error in result["errors"]:
        print(f"⚠️  [cleanup] {error}", file=sys.stderr)

    if not result["removed"] and not result["worktrees_removed"] and not args.dry_run:
        print("ℹ️  [cleanup] マージ済みの削除対象ブランチはありませんでした。")

    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
