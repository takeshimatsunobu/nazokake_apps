"""
tools/benchmark/container_runner.py
=====================================
Dockerサンドボックス内のENTRYPOINT。ホスト側のLLM推論には一切関与せず、以下だけを行う:
  1. 読み取り専用マウントされたfixtureを書き込み可能な/workspaceへコピーする。
  2. 修正前(baseline)のPytestを実行する。
  3. ホストからsys.stdin経由で受け取ったtask(Nazo-Agentがホスト側で生成したAST置換
     指示)をtools/ast_modifier.pyへ適用する。この適用の直前・直後で/workspace全体の
     ファイルハッシュをスナップショットし、差分(Epic 2 5次元評価ゲートの
     「副作用(Blast Radius)」)を検出する。
  4. 修正後(postfix)のPytestを実行する。

【instructions/156: ファイルマウント廃止とNDJSONストリーミングI/O】
Rootless Dockerにおけるバインドマウントのレースコンディション(instructions/149-155で
対処してきたsubuid/権限問題群)を根本的に回避するため、ホストとコンテナ間の結果の
受け渡しに書き込み可能なファイル共有(--output-dir)を一切使わない。代わりに、
結果が1件確定するごとに1行のJSON(NDJSON)としてsys.stderrへリアルタイムでflushする。
テスト対象コード自身が吐き出す生ログ(汚染データ、pytestやast_modifier.pyの
stdout/stderr)はsys.stdoutへそのまま流し、結果データチャネル(stderr)と厳格に
分離する。ホスト側(run_benchmark.py)はこのstderrを行単位でストリーム読み込みし、
コンテナが途中でクラッシュしても、それまでに受信済みの行はホスト側に保全される。

【instructions/157: 入力側マウントの全廃と双方向IPCへの回帰】タスクデータの受け渡しも
読み取り専用マウント(-v ...:/mnt/task:ro)経由のtask.jsonファイル読み込みを廃止し、
ホストがsys.stdinへ直接ストリーム注入するJSON文字列をsys.stdin.read()で受け取る
方式へ移行した。入力側マウントのパーミッションを緩和するのではなく、マウント自体を
無くすことでRootless Docker特有の権限問題をアーキテクチャ的に再発させない。
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WORKSPACE = Path("/workspace")


def _emit(event: dict) -> None:
    """結果イベントを1行のNDJSONとしてsys.stderrへ書き出し、直ちにflushする。

    テスト対象コードの生ログ(sys.stdout)と厳格に分離された、このコンテナと
    ホスト側run_benchmark.pyとの唯一の結果データチャネル。
    """
    sys.stderr.write(json.dumps(event, ensure_ascii=False) + "\n")
    sys.stderr.flush()


def _run_pytest(label: str) -> dict:
    """Pytestを実行する。標準出力・標準エラーはリダイレクトせずこのプロセス自身の
    sys.stdoutへ直接流す(テスト対象コードの生ログを汚染データとして結果チャネル
    (stderr)から分離するため)。JUnit XMLはコンテナ内の一時ファイルへ出力後、
    その内容を読み取ってから即座に削除する(ホストとのファイル共有は行わない)。
    """
    with tempfile.TemporaryDirectory() as junit_tmp_dir:
        junit_path = Path(junit_tmp_dir) / f"{label}.xml"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                ".",
                "-q",
                "-p",
                "no:cacheprovider",
                f"--junitxml={junit_path}",
            ],
            cwd=str(WORKSPACE),
            stdout=sys.stdout,
            stderr=subprocess.STDOUT,
        )
        junit_xml = junit_path.read_text(encoding="utf-8") if junit_path.exists() else ""
    return {"returncode": result.returncode, "junit_xml": junit_xml}


def _snapshot_files(root: Path) -> dict[str, str]:
    """root以下の全ファイルの、rootからの相対パス -> sha256ハッシュの対応表を作る。

    git等の外部ツールに依存せず(このイメージにgitは入っていない)、AST置換適用の
    直前・直後でこれを2回取ることで、意図しない副作用(修正対象外ファイルへの
    書き込み)を検出する(Epic 2「Blast Radius」)。
    """
    snapshot = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            snapshot[str(path.relative_to(root))] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return snapshot


def _diff_snapshots(before: dict[str, str], after: dict[str, str]) -> list[str]:
    """2つのスナップショットを比較し、追加・変更・削除されたファイルの相対パス一覧を返す。"""
    changed = {path for path, digest in after.items() if before.get(path) != digest}
    changed.update(path for path in before if path not in after)
    return sorted(changed)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture-dir", required=True)
    parser.add_argument(
        "--ast-modifier",
        required=True,
        help="ホストのtools/ast_modifier.pyへの読み取り専用マウント済みパス",
    )
    args = parser.parse_args()

    # 【絶対制約】コンテナは常に--rmで起動され(かつ/workspace自体はホストからマウント
    # されない、Dockerfileがビルド時にmkdir+chownしたイメージ内の一時ディレクトリ)、
    # 起動毎に必ず空の状態から始まる。
    #
    # shutil.copytree自体(copy_function=shutil.copyを指定してもディレクトリの
    # アトリビュートコピーは避けられない)が、読み取り専用マウント(-v ...:/mnt/fixture:ro)
    # 由来のfixtureを非rootの実行ユーザー(sandboxuser)でコピーする際にPermissionErrorを
    # 起こす原因になっていたため、shutil.copytreeを完全に廃止し、rglobによる手動
    # トラバーサル+shutil.copyfile(データ実体のみ、権限メタデータを一切コピーしない)へ
    # 置き換えた。
    fixture_dir = Path(args.fixture_dir)
    for src_path in fixture_dir.rglob("*"):
        dest_path = WORKSPACE / src_path.relative_to(fixture_dir)
        if src_path.is_dir():
            dest_path.mkdir(parents=True, exist_ok=True)
        else:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src_path, dest_path)

    baseline = _run_pytest("baseline")
    _emit({"event": "baseline_result", **baseline})

    # 【instructions/157】タスクデータは読み取り専用マウント済みファイルではなく、
    # ホストプロセスがdocker run -iのstdinへ直接書き込んだJSON文字列として届く。
    # ホスト側(run_benchmark.py)が書き込み後にproc.stdin.close()するため、
    # read()はEOFまで正しくブロック・完走する。
    task = json.loads(sys.stdin.read())
    # 職人ロール(小型モデル)がfile_pathを取り違えて出力するリスクに備え、実際に
    # 適用するファイルパスは常にこのコンテナのワークスペースパスで上書きする
    # (tools/agent_graph.pyのapply_nodeと同じ防御パターン)。
    task["file_path"] = str(WORKSPACE / "buggy.py")
    resolved_task_path = WORKSPACE / "_resolved_task.json"
    resolved_task_path.write_text(
        json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Epic 2 5次元評価ゲート「Blast Radius」: AST置換の適用直前の状態をスナップショット。
    before_snapshot = _snapshot_files(WORKSPACE)

    apply_result = subprocess.run(
        [sys.executable, args.ast_modifier, str(resolved_task_path)],
        stdout=sys.stdout,
        stderr=subprocess.STDOUT,
    )

    # 適用直後の状態と比較し、変更されたファイル一覧を送出する(対象ファイル以外への
    # 副作用の有無をホスト側run_benchmark.pyが判定できるようにする)。
    after_snapshot = _snapshot_files(WORKSPACE)
    changed_files = _diff_snapshots(before_snapshot, after_snapshot)
    _emit({"event": "blast_radius", "changed_files": changed_files})
    _emit(
        {
            "event": "apply_result",
            "returncode": apply_result.returncode,
            "task_used": task,
        }
    )

    postfix = _run_pytest("postfix")
    _emit({"event": "postfix_result", **postfix})

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        import traceback

        traceback.print_exc()
        sys.exit(1)
