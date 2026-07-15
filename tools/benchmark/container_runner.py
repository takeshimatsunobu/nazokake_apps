"""
tools/benchmark/container_runner.py
=====================================
Dockerサンドボックス内のENTRYPOINT。ホスト側のLLM推論には一切関与せず、以下だけを行う:
  1. 読み取り専用マウントされたfixtureを書き込み可能な/workspaceへコピーする。
  2. 修正前(baseline)のPytestを実行し、JUnit XMLへ記録する。
  3. 読み取り専用マウントされたtask.json(Nazo-Agentがホスト側で生成したAST置換指示)を
     tools/ast_modifier.pyへ適用する。
  4. 修正後(postfix)のPytestを実行し、JUnit XMLへ記録する。
成功/失敗の判定やメトリクス計算はホスト側(run_benchmark.py)が、書き込み可能な
--output-dir から読み取ったJUnit XML/適用結果を元に行う(このスクリプト自身は
コンテナのexit codeで全体の成否を語らない。fixture不在等の想定外の例外時のみ1を返す)。
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

WORKSPACE = Path("/workspace")


def _run_pytest(junit_path: Path) -> dict:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", ".", "-q", f"--junitxml={junit_path}"],
        cwd=str(WORKSPACE),
        capture_output=True,
        text=True,
    )
    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture-dir", required=True)
    parser.add_argument("--task-json", required=True)
    parser.add_argument(
        "--ast-modifier",
        required=True,
        help="ホストのtools/ast_modifier.pyへの読み取り専用マウント済みパス",
    )
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if WORKSPACE.exists():
        shutil.rmtree(WORKSPACE)
    shutil.copytree(args.fixture_dir, WORKSPACE)

    baseline = _run_pytest(output_dir / "baseline.xml")
    (output_dir / "baseline_stdout.txt").write_text(
        baseline["stdout"] + "\n" + baseline["stderr"], encoding="utf-8"
    )

    task = json.loads(Path(args.task_json).read_text(encoding="utf-8"))
    # 職人ロール(小型モデル)がfile_pathを取り違えて出力するリスクに備え、実際に
    # 適用するファイルパスは常にこのコンテナのワークスペースパスで上書きする
    # (tools/agent_graph.pyのapply_nodeと同じ防御パターン)。
    task["file_path"] = str(WORKSPACE / "buggy.py")
    resolved_task_path = WORKSPACE / "_resolved_task.json"
    resolved_task_path.write_text(
        json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    apply_result = subprocess.run(
        [sys.executable, args.ast_modifier, str(resolved_task_path)],
        capture_output=True,
        text=True,
    )
    (output_dir / "apply_meta.json").write_text(
        json.dumps(
            {
                "returncode": apply_result.returncode,
                "stdout": apply_result.stdout,
                "stderr": apply_result.stderr,
                "task_used": task,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    postfix = _run_pytest(output_dir / "postfix.xml")
    (output_dir / "postfix_stdout.txt").write_text(
        postfix["stdout"] + "\n" + postfix["stderr"], encoding="utf-8"
    )

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        import traceback

        traceback.print_exc()
        sys.exit(1)
