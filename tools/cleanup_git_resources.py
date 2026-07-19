"""
tools/cleanup_git_resources.py
=================================
Nazo-Agentの自律エスカレーション(tools/agent_graph.py の managed_git_worktree)は、
隔離用の物理worktreeディレクトリ自体は使用直後に必ず破棄する(finallyブロック)ものの、
レビュー用に残す設計の escalation/* ブランチ自体は破棄しない。CTOエスカレーションが
無人稼働で走るたびにブランチが増え続けるため、放置するとローカルGitのメタデータ(refs)が
肥大化しストレージを圧迫する(instructions/175、堅牢化はinstructions/176)。

【絶対基準: マージ状態】経過時間による推測削除(例:「作成から7日経過したら削除」)は、
レビューが長引いているだけの正当なブランチを誤って破棄するシステム破壊の温床となるため
禁止する。「本流(main/master)へ既に取り込まれた」という決定論的な事実のみを削除の
絶対基準とし、以下2種の判定手段を組み合わせる:

  1. `git branch --merged <main/master>` — Fast-forward/Merge commitで本流の祖先に
     取り込まれたブランチを検出する(標準的な祖先関係チェック)。
  2. `git cherry <main/master> <branch>` — Squash Merge等でコミットハッシュが変わり、
     ブランチのコミットが本流の祖先にならないケースをカバーする(instructions/176)。
     ブランチの各コミットについて、本流側に等価な変更(パッチID相当)が既に存在するかを
     判定し、既存分は"-"、未反映の独自変更は"+"として一覧される。1件でも"+"が
     付くコミットがあれば「まだ本流に取り込まれていない独自の変更が残っている」と
     みなし、安全側に倒して削除対象から外す(保護)。

いずれの判定でも合致しなかったブランチ(レビュー中・実験中の未マージブランチを含む)は
このコードパスから一切操作しない(保護対象)。

対象は escalation/*(instructions/124のCTOエスカレーション)および draft/*(過去に
tools/nazo_agent.pyが生成していた隔離ドラフトブランチの残存物)のプレフィックスに
合致するブランチのみ。main/master自身や開発者の作業ブランチ等はプレフィックスに
合致しないため対象外。

worktree自体はmanaged_git_worktreeのfinallyで既に破棄されている想定だが、プロセスが
SIGKILL等で強制終了した場合はfinallyが走らず`git worktree list`上の登録が残存し得る。
worktreeが紐づいたブランチは`git branch -d`が失敗するため、対象ブランチにworktreeが
紐づいている場合は必ず`git worktree remove --force`を先に実行してからブランチを削除する。

【可観測性(instructions/176)】削除対象の判定理由(祖先関係によるマージ済みか、
Squash Merge検出によるものか、あるいは未マージのため保護したか)、削除したworktreeの
物理パス、削除したブランチ名を、標準出力へ全件ロギングする(このモジュール専用の
loggerにStreamHandlerを明示的に付与し、呼び出し元プロセスのlogging設定に依存せず
必ず出力されるようにしている)。

【Dry-run(instructions/176)】環境変数 DRY_RUN=true が設定されている場合、または
CLI引数 --dry-run 指定時は、実際のgit worktree remove/git branch -dを一切実行せず、
削除予定の一覧をログ出力するだけに留める。

使い方:
    uv run python tools/cleanup_git_resources.py             # 実際に削除を実行
    uv run python tools/cleanup_git_resources.py --dry-run   # 削除対象の一覧表示のみ
    DRY_RUN=true uv run python tools/cleanup_git_resources.py  # 同上(環境変数版)
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# 削除対象とみなすブランチ名のプレフィックス。これに合致しないブランチ
# (main/master、開発者の作業ブランチ等)はマージ済みと判定されても一切操作しない。
TARGET_PREFIXES = ("escalation/", "draft/")

# このモジュール専用のlogger。呼び出し元(mlops_trigger.py等)や実行時のlogging設定に
# 依存せず、削除判断の理由を必ず標準出力へ記録するため、専用のStreamHandlerを明示的に
# 付与しroot loggerへは伝播させない(他モジュールのログ設定を汚染しないため)。
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(_handler)
    logger.propagate = False


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


def _is_dry_run(explicit: bool | None) -> bool:
    """dry-runの有効判定。呼び出し元がdry_runを明示指定した場合はそれを優先し、
    未指定(None)の場合のみ環境変数 DRY_RUN=true(大文字小文字は無視)にフォール
    バックする(instructions/176)。これにより、tools/mlops_trigger.py側の既存の
    呼び出し `cleanup_merged_git_resources()`(引数なし)を変更しなくても、
    スケジューラ環境でDRY_RUN=trueを設定するだけで安全に検証運用できる。
    """
    if explicit is not None:
        return explicit
    return os.environ.get("DRY_RUN", "").strip().lower() == "true"


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


def _list_target_branches(repo_root: Path) -> list[str]:
    """TARGET_PREFIXESに合致するブランチ名を、マージ状態を問わず全て列挙する
    (この後の判定ロジックが、各ブランチについて個別にマージ済みか保護対象かを決める)。
    """
    result = _run_git(
        ["branch", "--list", *[f"{prefix}*" for prefix in TARGET_PREFIXES]], repo_root
    )
    if result.returncode != 0:
        raise RuntimeError(f"git branch --listの実行に失敗しました: {result.stderr.strip()}")

    branches = []
    for line in result.stdout.splitlines():
        # `git branch`の出力は先頭2文字がインジケータ("* "=カレント、"+ "=他worktreeで
        # チェックアウト中、"  "=通常)のため、必ず先頭から剥がす。
        name = line[2:].strip() if len(line) > 2 else line.strip()
        if name:
            branches.append(name)
    return branches


def _list_merged_branch_names(repo_root: Path, main_branch: str) -> set[str]:
    """`git branch --merged <main_branch>` の結果をブランチ名の集合として返す
    (Fast-forward/Merge commitにより本流の祖先関係が成立しているブランチ)。
    """
    result = _run_git(["branch", "--merged", main_branch], repo_root)
    if result.returncode != 0:
        raise RuntimeError(
            f"git branch --mergedの実行に失敗しました: {result.stderr.strip()}"
        )

    names = set()
    for line in result.stdout.splitlines():
        name = line[2:].strip() if len(line) > 2 else line.strip()
        if name and name != main_branch:
            names.add(name)
    return names


def _is_squash_merged(repo_root: Path, main_branch: str, branch_name: str) -> bool:
    """`git branch --merged`で捕捉できないSquash Merge済みブランチを、`git cherry`の
    等価パッチ判定で検出する(instructions/176)。

    Squash Mergeはブランチの複数コミットを1個の新規コミットとして本流へ適用するため、
    ブランチのコミット自体は本流の祖先にならず`git branch --merged`は検知できない。
    `git cherry <main_branch> <branch_name>`は、ブランチの各コミットについて「パッチ
    内容が本流側の履歴に等価な変更として既に存在するか」を判定し、既に存在するコミット
    には"-"、存在しない(本流へ未反映の独自変更)コミットには"+"を付けて一覧する。
    1件でも"+"が付くコミットがあれば、そのブランチにはまだ本流へ取り込まれていない
    独自の変更が残っているとみなし、安全側に倒してFalse(削除禁止)を返す。
    """
    result = _run_git(["cherry", main_branch, branch_name], repo_root)
    if result.returncode != 0:
        # cherry自体が失敗した場合(共通祖先が無い等)は判定不能とみなし、安全側に
        # 倒して「マージ済みとは断定できない」= 削除禁止とする。
        return False

    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        # 本流との差分コミットが無い(=既に本流の祖先。--mergedで捕捉されるはずだが、
        # 念のためここでも「差分なし=マージ済み」として扱う)。
        return True
    return all(line.startswith("-") for line in lines)


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


def cleanup_merged_git_resources(
    repo_root: Path | None = None, *, dry_run: bool | None = None
) -> dict:
    """本流(main/master)へマージ済みのescalation/*・draft/*ブランチ(および紐づく
    worktree、残存していれば)を安全に削除する(instructions/175、堅牢化はinstructions/176)。

    マージ判定は「祖先関係(git branch --merged)」と「Squash Merge等価パッチ検出
    (git cherry)」の2種を併用し、いずれにも合致しないブランチ(未マージ)は構造的に
    一切操作しない(保護対象)。dry_run(明示指定が無い場合は環境変数DRY_RUN=trueに
    フォールバック)がTrueの場合は削除対象を特定してログ表示するだけで、実際のgit
    worktree remove/git branch -dは実行しない。
    {"removed": [...], "worktrees_removed": [...], "protected": [...], "errors": [...]}
    を返す。
    """
    root = repo_root or BASE_DIR
    effective_dry_run = _is_dry_run(dry_run)
    result: dict = {
        "removed": [],
        "worktrees_removed": [],
        "protected": [],
        "errors": [],
    }

    try:
        main_branch = _resolve_main_branch(root)
        candidates = _list_target_branches(root)
        merged_by_ancestry = _list_merged_branch_names(root, main_branch)
    except RuntimeError as e:
        logger.error(f"⚠️  [cleanup] {e}")
        result["errors"].append(str(e))
        return result

    if not candidates:
        logger.info(
            f"ℹ️  [cleanup] {TARGET_PREFIXES}に合致するブランチは存在しませんでした"
            "(クリーンアップ不要)。"
        )
        return result

    for branch_name in candidates:
        is_ancestry_merged = branch_name in merged_by_ancestry
        if is_ancestry_merged:
            reason = "git branch --merged: 祖先関係(Fast-forward/Merge commit)でマージ済み"
        elif _is_squash_merged(root, main_branch, branch_name):
            reason = "git cherry: 全コミットが等価パッチとして本流へ取り込み済み(Squash Merge検出)"
        else:
            logger.info(
                f"🛡️  [cleanup] 保護: {branch_name} は本流へ未反映の変更を含むため、"
                "削除対象から除外します。"
            )
            result["protected"].append(branch_name)
            continue

        logger.info(f"🔎 [cleanup] 削除対象と判定: {branch_name} ({reason})")

        worktree_path = _find_worktree_path_for_branch(root, branch_name)
        if worktree_path is not None:
            if effective_dry_run:
                logger.info(
                    f"🧪 [dry-run] worktree削除予定: {worktree_path} (branch={branch_name})"
                )
            else:
                wt_result = _run_git(
                    ["worktree", "remove", "--force", str(worktree_path)], root
                )
                if wt_result.returncode != 0:
                    error_message = (
                        f"{branch_name}: git worktree removeに失敗しました: "
                        f"{wt_result.stderr.strip()}"
                    )
                    logger.error(f"⚠️  [cleanup] {error_message}")
                    result["errors"].append(error_message)
                    # worktreeが紐づいたままだとgit branch -dが必ず失敗するため、
                    # このブランチのブランチ削除は諦めて次のブランチへ進む
                    # (安全側に倒し、中途半端な状態(worktreeもブランチも残存)
                    # として次回サイクルの再試行に委ねる)。
                    continue
                result["worktrees_removed"].append(str(worktree_path))
                logger.info(
                    f"🗑️  [cleanup] worktreeを削除しました: {worktree_path} "
                    f"(branch={branch_name})"
                )

        if effective_dry_run:
            logger.info(f"🧪 [dry-run] ブランチ削除予定: {branch_name} ({reason})")
            continue

        # 祖先関係(-d)で安全に判定できるケースはgit自身の二重チェックに委ねてそのまま
        # 使うが、Squash Merge検出(-D)のケースはブランチのコミットが本流の祖先で
        # ないため、gitの標準的な-dは常に"not fully merged"として拒否してしまう
        # (git branch -dの安全確認はcherryの等価パッチ判定を認識しない)。この経路へ
        # 到達している時点で既にgit cherryによる独自の安全性検証は完了しているため、
        # -D(強制削除)を用いる。
        delete_flag = "-d" if is_ancestry_merged else "-D"
        branch_result = _run_git(["branch", delete_flag, branch_name], root)
        if branch_result.returncode != 0:
            error_message = (
                f"{branch_name}: git branch {delete_flag}に失敗しました: "
                f"{branch_result.stderr.strip()}"
            )
            logger.error(f"⚠️  [cleanup] {error_message}")
            result["errors"].append(error_message)
            continue
        result["removed"].append(branch_name)
        logger.info(f"🗑️  [cleanup] マージ済みブランチを削除しました: {branch_name} ({reason})")

    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="本流へマージ済み(祖先関係またはSquash Merge検出)のescalation/*・"
        "draft/*ブランチ/worktreeを削除する"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=None,
        help="実際に削除せず、削除対象の一覧表示のみ行う(環境変数DRY_RUN=trueでも同等)",
    )
    args = parser.parse_args()

    result = cleanup_merged_git_resources(dry_run=args.dry_run)

    if not result["errors"] and not result["removed"] and not result["worktrees_removed"]:
        logger.info("ℹ️  [cleanup] マージ済みの削除対象ブランチはありませんでした。")

    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
