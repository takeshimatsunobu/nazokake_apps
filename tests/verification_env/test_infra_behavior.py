"""
tests/verification_env/test_infra_behavior.py
=================================================
検証サーバー移行(instructions/145)の振る舞い検証。静的解析(Linter)のパスのみを完了
条件とせず、実際の動的な振る舞い(タイミング・並行I/O・実データ)で証明する。

Docker/systemd/NVIDIA Container Toolkitが利用できないこの開発環境(Windows、Docker未導入)
では、それらに依存するテストはpytest.skipで明示的にスキップする(「未検証」と「検証して
合格」を区別する。tools/benchmark/run_benchmark.py._require_docker_or_die()と同じ
「測定不能なら安全側に倒す」思想をテスト設計にも適用し、無条件成功で済ませない)。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from tools import export_metrics, mlops_common  # noqa: E402
from tools.benchmark import run_benchmark as rb  # noqa: E402
from tools.compile_knowledge import KNOWLEDGE_BASE_PATH  # noqa: E402
from tools.knowledge_retriever import retrieve_experiences  # noqa: E402


def test_cgroup_delegation_is_active():
    """systemdのcgroup v2 delegation(Delegate=yes)が実際に有効かを動的に確認する。

    ファイル(delegate.conf)の存在確認だけでは「配置した」ことしか分からないため、
    systemctl show で実際にsystemdへ反映されている設定値そのものを確認する。
    """
    if shutil.which("systemctl") is None:
        pytest.skip(
            "systemctlが利用できない環境です(この開発マシンにはRootless Docker"
            "検証サーバーが存在しません)。"
        )
    result = subprocess.run(
        ["systemctl", "show", f"user@{os.getuid()}.service", "-p", "Delegate"],
        capture_output=True,
        text=True,
    )
    assert "Delegate=yes" in result.stdout


def test_nvidia_toolkit_hook_and_gpu_visible():
    """NVIDIA Container Toolkitのno-cgroups設定と、実際のGPUコンテナ起動を動的に確認する。"""
    if shutil.which("docker") is None or shutil.which("nvidia-ctk") is None:
        pytest.skip("dockerまたはnvidia-ctkが利用できない環境です。")
    config_result = subprocess.run(
        ["nvidia-ctk", "config", "--config=/etc/nvidia-container-runtime/config.toml"],
        capture_output=True,
        text=True,
    )
    assert "no-cgroups = true" in config_result.stdout
    gpu_result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--gpus",
            "all",
            "nvidia/cuda:12.4.1-base-ubuntu22.04",
            "nvidia-smi",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert gpu_result.returncode == 0
    assert "NVIDIA-SMI" in gpu_result.stdout


def test_vram_lock_serializes_concurrent_pipelines(monkeypatch, tmp_path):
    """VRAMロック(filelock)が2つの呼び出し元を実際に直列化することをタイミングで確認する。

    本番のVRAM_LOCK_PATHには触れず、tmp_pathへ差し替えたロックファイルで検証する。
    """
    lock_path = tmp_path / "test.vram.lock"
    monkeypatch.setattr(mlops_common, "VRAM_LOCK_PATH", lock_path)

    first_lock = mlops_common.acquire_vram_lock_with_backoff(max_wait_sec=2)
    second_acquired_at: list[float] = []
    start = time.monotonic()

    def acquire_second() -> None:
        second_lock = mlops_common.acquire_vram_lock_with_backoff(max_wait_sec=2)
        second_acquired_at.append(time.monotonic())
        second_lock.release()

    thread = threading.Thread(target=acquire_second)
    thread.start()

    time.sleep(1.0)
    assert not second_acquired_at, "1番目が保持中にも関わらず2番目が即座に取得できてしまった"

    first_lock.release()
    thread.join(timeout=10)

    assert second_acquired_at, "1番目の解放後も2番目が取得できなかった"
    assert second_acquired_at[0] - start >= 1.0


def test_atomic_dashboard_write_survives_concurrent_reads(monkeypatch, tmp_path):
    """アトミック書き込み(fsync+os.replace)が並行読み取り下で不完全なJSONを晒さないことを
    実際の並行I/Oで確認する。本番のmetrics.jsonには触れず、tmp_pathへ差し替えて検証する。
    """
    tmp_output = tmp_path / "metrics.json"
    tmp_tmp = tmp_path / "metrics.tmp.json"
    monkeypatch.setattr(export_metrics, "METRICS_OUTPUT_PATH", tmp_output)
    monkeypatch.setattr(export_metrics, "METRICS_TMP_PATH", tmp_tmp)

    stop = threading.Event()
    read_errors: list[str] = []

    def writer() -> None:
        while not stop.is_set():
            try:
                export_metrics.export_metrics()
            except PermissionError:
                # reader()と同じ理由(Windows特有の一時的な共有違反): 読み取り側が
                # ファイルを開いている瞬間にos.replace()が競合し得る。本番環境
                # (Linux/Cloud Run)ではrenameの完全なアトミック性によりこの競合は
                # 起こらない。実際のMLOpsパイプラインもVRAM_LOCK_PATHにより
                # export_metrics()の呼び出し自体が直列化されているため、この
                # タイトループ的な競合は本テストの意図的な負荷でのみ発生する。
                continue

    def reader() -> None:
        while not stop.is_set():
            if not tmp_output.exists():
                continue
            try:
                data = json.loads(tmp_output.read_text(encoding="utf-8"))
            except PermissionError:
                # Windows特有の一時的な共有違反: os.replace()によるすげ替えの瞬間に
                # 読み取り側がopenを試みると発生し得る(POSIXのrenameは並行openに対して
                # 完全にアトミックだが、Windows/NTFSはこの一瞬だけファイルハンドルが
                # 競合し得る)。データの破損ではなくOSレベルの一時的な競合のため、
                # 本番想定のLinux環境には無関係(本プロジェクトのデプロイ先はCloud Run)。
                # データ不整合(JSONDecodeError/schema_version不一致)とは区別し、
                # 単に次のループへ再試行する。
                continue
            except json.JSONDecodeError as e:
                read_errors.append(f"JSONDecodeError: {e}")
                continue
            if data.get("schema_version") != "1.0":
                read_errors.append(f"unexpected schema_version: {data.get('schema_version')!r}")

    writer_thread = threading.Thread(target=writer)
    reader_thread = threading.Thread(target=reader)
    writer_thread.start()
    reader_thread.start()
    time.sleep(1.0)
    stop.set()
    writer_thread.join(timeout=5)
    reader_thread.join(timeout=5)

    assert not read_errors, f"リーダーが不完全/不整合なJSONを観測した: {read_errors}"


def test_6d_quality_gate_time_to_quality_parity():
    """第6次元(時間対品質パリティ)がquality_gate_time_to_quality_parity_maxに従って
    正しく合否判定されることを、N/A・合格・比率超過・品質未達・測定不能の5経路で確認する。
    """
    base_aggregate = {
        "success_rate": 0.95,
        "avg_regression_rate": 0.0,
        "avg_complexity_growth_rate": 0.05,
        "max_retry_count": 1,
        "max_blast_radius": 0,
    }

    no_escalation = {
        "aggregate": {**base_aggregate, "qwen_only_avg_latency_ms": 1000},
        "results": [{"fixture": "a", "cto_escalated": False, "latency_ms": 900, "success": True}],
    }
    gate = rb.evaluate_6d_quality_gate(no_escalation)
    assert gate["passed"] is True
    assert gate["dimensions"]["time_to_quality_parity"]["applicable"] is False

    within_ratio = {
        "aggregate": {**base_aggregate, "qwen_only_avg_latency_ms": 1000},
        "results": [
            {"fixture": "a", "cto_escalated": False, "latency_ms": 1000, "success": True},
            {"fixture": "b", "cto_escalated": True, "latency_ms": 2500, "success": True},
        ],
    }
    assert rb.evaluate_6d_quality_gate(within_ratio)["passed"] is True

    exceeds_ratio = {
        "aggregate": {**base_aggregate, "qwen_only_avg_latency_ms": 1000},
        "results": [
            {"fixture": "a", "cto_escalated": False, "latency_ms": 1000, "success": True},
            {"fixture": "b", "cto_escalated": True, "latency_ms": 5000, "success": True},
        ],
    }
    assert rb.evaluate_6d_quality_gate(exceeds_ratio)["passed"] is False

    fast_but_failed = {
        "aggregate": {**base_aggregate, "qwen_only_avg_latency_ms": 1000},
        "results": [
            {"fixture": "a", "cto_escalated": False, "latency_ms": 1000, "success": True},
            {"fixture": "b", "cto_escalated": True, "latency_ms": 1200, "success": False},
        ],
    }
    assert rb.evaluate_6d_quality_gate(fast_but_failed)["passed"] is False

    unmeasurable_baseline = {
        "aggregate": {**base_aggregate, "qwen_only_avg_latency_ms": None},
        "results": [{"fixture": "b", "cto_escalated": True, "latency_ms": 1200, "success": True}],
    }
    assert rb.evaluate_6d_quality_gate(unmeasurable_baseline)["passed"] is False


def test_experience_replay_available_after_provisioning():
    """知識ベースが事前ビルド済みであり、既知のクエリに対して実際に検索結果を返すことを
    (モック無しで)確認する。
    """
    if not KNOWLEDGE_BASE_PATH.exists():
        pytest.skip(
            "tools/ai_knowledge_base.json が未ビルドです。"
            "先に `uv run python tools/compile_knowledge.py` を実行してください。"
        )
    results = retrieve_experiences(
        "Docker sandbox infrastructure error exit code 125 sys.exit run_benchmark.py",
        top_k=3,
    )
    assert results, "既知のクエリに対して検索結果が空だった"
    assert any(r.get("id") == "136" for r in results)
