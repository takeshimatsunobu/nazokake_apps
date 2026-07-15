"""
tools/benchmark/run_benchmark.py
==================================
Nazo-Agentベンチマークハーネスのホスト側ドライバ。

役割分担:
  - ホスト: LLM推論(tools/agent_graph.pyが実装する現場監督→職人→検証の自律修復ループの
    「推論のみ」部分)を実際に呼び出し、AST置換JSON(修復タスク)を生成する。
  - Docker: 生成されたタスクの適用(tools/ast_modifier.py)とPytest実行は必ずコンテナ内
    でのみ行う(ホストのファイルシステムには一切書き込まない)。

tools/agent_graph.py の supervisor_node/craftsman_node/validate_node をそのまま再利用し、
apply_node/gemma_fallback_node/reporter_node を含まない推論専用の小さなLangGraphを
ここに構築する(agent_graph.py自体は無改変)。
"""

import argparse
import ast
import json
import subprocess
import sys
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

# `python tools/benchmark/run_benchmark.py` のように直接実行すると sys.path[0] は
# tools/benchmark/ 自身になり、`from tools import agent_graph`(リポジトリ直下のパッケージ
# として参照する絶対import)が ModuleNotFoundError: No module named 'tools' になる。
# tools/nazo_agent.pyと同じ対処(リポジトリルートを明示的にsys.pathへ追加)を行う。
BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# tools.config が起動時にOLLAMA_HOST等をFail-Fast検証し、os.environへ正規化済みの値を
# 反映する(以前この場所にあった無検証のos.environ["OLLAMA_HOST"]=...という
# ハードコードされたワークアラウンドは廃止し、この一元化された設定モジュールに委ねる)。
# ChatOllamaを構築する`tools.agent_graph`より必ず先にimportする必要がある。
from tools import config  # noqa: E402, F401
from langgraph.graph import END, StateGraph  # noqa: E402

from tools import agent_graph  # noqa: E402

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
REPORTS_DIR = Path(__file__).resolve().parent / "reports"
DOCKER_IMAGE = "nazo-benchmark-sandbox"
TARGET_TEST_NAME = "test_target_behavior"


def _route_inference_only(state: agent_graph.AuditState) -> str:
    if not state.get("last_validation_error"):
        return "done"
    if state["retry_count"] >= agent_graph.MAX_JSON_RETRIES:
        return "give_up"
    return "craftsman"


def build_inference_only_graph():
    """Nazo-Agentの現場監督→職人→検証ループのみを実行するLangGraph。

    apply_node/gemma_fallback_node/reporter_nodeは一切含まない=推論の結果得られる
    AST置換JSONをホスト上のファイルへ書き込む経路が構造的に存在しない(適用は必ず
    Dockerコンテナ内でのみ行う、というこのベンチマークの隔離要件をグラフの配線
    そのもので保証する)。
    """
    graph = StateGraph(agent_graph.AuditState)
    graph.add_node("supervisor", agent_graph.supervisor_node)
    graph.add_node("craftsman", agent_graph.craftsman_node)
    graph.add_node("validate", agent_graph.validate_node)
    graph.set_entry_point("supervisor")
    graph.add_edge("supervisor", "craftsman")
    graph.add_edge("craftsman", "validate")
    graph.add_conditional_edges(
        "validate",
        _route_inference_only,
        {"done": END, "craftsman": "craftsman", "give_up": END},
    )
    return graph.compile()


def run_inference(file_path: str, source: str, error_log: str) -> dict:
    """指定コードに対しNazo-Agentの推論(現場監督→職人→検証)を1回実行し、最終stateを返す。"""
    app = build_inference_only_graph()
    initial_state: agent_graph.AuditState = {
        "file_path": file_path,
        "current_code": source,
        "error_log": error_log,
        "audit_history": [],
        "diagnosis": "",
        "retry_count": 0,
        "last_validation_error": "",
        "raw_json_text": "",
        "result_message": "",
        "escalated": False,
        "dead_letter_path": "",
    }
    return app.invoke(initial_state)


def _ast_stats(target_name: str, source: str) -> dict | None:
    """source中のtarget_name関数/クラスのASTノード数・行数を計測する。

    sourceがそもそもパース不能(SyntaxErrorのfixture等)な場合や、target_nameの
    ノードが見つからない場合はNoneを返す(呼び出し元は"note"で理由を残す)。
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if getattr(node, "name", None) == target_name:
            return {
                "node_count": sum(1 for _ in ast.walk(node)),
                "line_count": (node.end_lineno or node.lineno) - node.lineno + 1,
            }
    return None


def compute_code_complexity(
    target_name: str, original_source: str, new_code: str
) -> dict:
    original = _ast_stats(target_name, original_source)
    new = _ast_stats(target_name, new_code)
    note = None
    if original is None:
        note = (
            "元のコードから対象ノードのAST統計を計算できませんでした(SyntaxError等)。"
        )
    elif new is None:
        note = "修正後のコード(new_code)から対象ノードのAST統計を計算できませんでした。"
    return {
        "target_name": target_name,
        "original": original,
        "new": new,
        "node_count_delta": (
            new["node_count"] - original["node_count"] if original and new else None
        ),
        "line_count_delta": (
            new["line_count"] - original["line_count"] if original and new else None
        ),
        "note": note,
    }


def _parse_junit(xml_path: Path) -> dict:
    """JUnit XML(pytest --junitxml)をパースし、{テスト名: passed(bool)}へ変換する。

    ファイルが存在しない場合(コンテナ実行が行われなかった場合)は空dictを返す。
    """
    if not xml_path.exists():
        return {}
    root = ET.parse(xml_path).getroot()
    results = {}
    for testcase in root.iter("testcase"):
        name = testcase.get("name")
        failed = (
            testcase.find("failure") is not None or testcase.find("error") is not None
        )
        results[name] = not failed
    return results


def _run_in_docker(fixture_dir: Path, task: dict, output_dir: Path) -> str:
    """docker runでコンテナ内にfixtureをコピーし、AST置換の適用とPytest実行を行わせる。

    戻り値はdocker_stage文字列("completed" または "failed: <理由>")。dockerコマンド
    自体が存在しない場合もここでのみ捕捉し、呼び出し元(1fixtureの処理)を継続させる
    (1fixtureのDocker失敗で他のfixtureの処理をブロックしない)。
    """
    with tempfile.TemporaryDirectory() as task_tmp_dir:
        task_json_path = Path(task_tmp_dir) / "task.json"
        task_json_path.write_text(
            json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        cmd = [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{BASE_DIR / 'tools'}:/mnt/tools:ro",
            "-v",
            f"{BASE_DIR / 'packages'}:/mnt/packages:ro",
            "-v",
            f"{BASE_DIR / 'apps'}:/mnt/apps:ro",
            "-v",
            f"{fixture_dir}:/mnt/fixture:ro",
            "-v",
            f"{task_tmp_dir}:/mnt/task:ro",
            "-v",
            f"{output_dir}:/mnt/output:rw",
            DOCKER_IMAGE,
            "--fixture-dir",
            "/mnt/fixture",
            "--task-json",
            "/mnt/task/task.json",
            "--ast-modifier",
            "/mnt/tools/ast_modifier.py",
            "--output-dir",
            "/mnt/output",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
        except FileNotFoundError as e:
            return f"failed: {e}"

        if result.returncode != 0:
            stderr_snippet = result.stderr.strip()[:500]
            return (
                f"failed: docker run exited with {result.returncode}: {stderr_snippet}"
            )
        return "completed"


def run_fixture(name: str) -> dict:
    """1fixtureぶんの推論→Docker適用・テスト→メトリクス計算を実行する。"""
    fixture_dir = FIXTURES_DIR / name
    buggy_source = (fixture_dir / "buggy.py").read_text(encoding="utf-8")
    error_log = (fixture_dir / "error_log.txt").read_text(encoding="utf-8").strip()

    start = time.perf_counter()

    final_state = run_inference(
        file_path=str(fixture_dir / "buggy.py"),
        source=buggy_source,
        error_log=error_log,
    )

    result = {
        "fixture": name,
        "inference_outcome": None,
        "docker_stage": None,
        "success": None,
        "latency_ms": None,
        "regression": None,
        "code_complexity": None,
        "task": None,
    }

    if final_state.get("last_validation_error"):
        result["inference_outcome"] = "retries_exhausted"
        result["docker_stage"] = "skipped: no validated task"
        result["latency_ms"] = (time.perf_counter() - start) * 1000
        return result

    result["inference_outcome"] = "validated"
    task = json.loads(agent_graph._strip_code_fence(final_state["raw_json_text"]))
    result["task"] = task
    result["code_complexity"] = compute_code_complexity(
        task["target_name"], buggy_source, task["new_code"]
    )

    with tempfile.TemporaryDirectory() as output_dir_str:
        output_dir = Path(output_dir_str)
        result["docker_stage"] = _run_in_docker(fixture_dir, task, output_dir)
        result["latency_ms"] = (time.perf_counter() - start) * 1000

        if result["docker_stage"] == "completed":
            baseline = _parse_junit(output_dir / "baseline.xml")
            postfix = _parse_junit(output_dir / "postfix.xml")

            result["success"] = postfix.get(TARGET_TEST_NAME)

            previously_passing_sanity = [
                test_name
                for test_name, passed in baseline.items()
                if test_name != TARGET_TEST_NAME and passed
            ]
            regressed = [
                test_name
                for test_name in previously_passing_sanity
                if not postfix.get(test_name, False)
            ]
            result["regression"] = {
                "regressed_tests": regressed,
                "regression_rate": (
                    len(regressed) / len(previously_passing_sanity)
                    if previously_passing_sanity
                    else None
                ),
            }

    return result


def _check_docker_available() -> bool:
    try:
        subprocess.run(
            ["docker", "version"], capture_output=True, text=True, timeout=10
        )
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Nazo-Agentベンチマークハーネス")
    parser.add_argument(
        "--fixture", help="実行するfixture名(省略時はfixtures/配下の全て)"
    )
    args = parser.parse_args()

    if args.fixture:
        fixture_names = [args.fixture]
    else:
        fixture_names = sorted(p.name for p in FIXTURES_DIR.iterdir() if p.is_dir())

    if not fixture_names:
        print("実行対象のfixtureが見つかりませんでした。", file=sys.stderr)
        return 1

    docker_available = _check_docker_available()

    results = []
    for name in fixture_names:
        print(f"=== fixture: {name} ===")
        try:
            result = run_fixture(name)
        except Exception as e:  # noqa: BLE001 - 1fixtureの想定外failureで全体を止めない
            result = {
                "fixture": name,
                "inference_outcome": None,
                "docker_stage": None,
                "success": None,
                "latency_ms": None,
                "regression": None,
                "code_complexity": None,
                "task": None,
                "error": repr(e),
            }
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        results.append(result)

    successes = [r["success"] for r in results if r["success"] is not None]
    latencies = [r["latency_ms"] for r in results if r["latency_ms"] is not None]
    regression_rates = [
        r["regression"]["regression_rate"]
        for r in results
        if r.get("regression") and r["regression"]["regression_rate"] is not None
    ]

    report = {
        "run_id": uuid.uuid4().hex,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "docker_available": docker_available,
        "fixtures_run": fixture_names,
        "results": results,
        "aggregate": {
            "success_rate": (sum(successes) / len(successes)) if successes else None,
            "avg_latency_ms": (sum(latencies) / len(latencies)) if latencies else None,
            "avg_regression_rate": (
                sum(regression_rates) / len(regression_rates)
                if regression_rates
                else None
            ),
        },
    }

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_filename = f"benchmark_{report['timestamp'].replace(':', '-')}.json"
    report_path = REPORTS_DIR / report_filename
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"レポートを書き出しました: {report_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
