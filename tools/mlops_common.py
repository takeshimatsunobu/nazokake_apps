"""
tools/mlops_common.py
========================
tools/mlops_pipeline_nazo.py と tools/mlops_pipeline_agent.py が共有する低レベルの
プリミティブ(Epic 3)。

旧 tools/mlops_pipeline.py が単一のパイプラインとして持っていた「GPU予防クリーンアップ」
「サブプロセスのアトミックな起動」「VRAMグローバルロックの取得」を、2つの独立した
パイプラインへの分離後も重複させないためにここへ集約する。各パイプライン固有の
ステップ構成・品質ゲート判定ロジックは、この共通モジュールには置かない
(呼び出し元スクリプトの責務)。
"""

from __future__ import annotations

import locale
import os
import subprocess
import sys
from pathlib import Path

import filelock
import httpx
import psutil
import tenacity

from tools import process_manager
from tools.config import VRAM_LOCK_PATH, settings
from tools.exceptions import MLOpsInfrastructureError, PipelineExecutionError

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent.parent

# 【instructions/275: VRAM排他制御の防弾化】tools/mlops_pipeline_nazo.py /
# tools/mlops_pipeline_agent.py は、抽出・学習・評価の全ステップをrun_step()経由で
# サブプロセス実行する前に、この呼び出し元プロセス自身が既にVRAMロックを保持している
# (acquire_vram_lock_with_backoff()参照)。学習エントリーポイント
# (tools/train_nazo_model.py / tools/train_agent_model.py)は単独実行時にも自衛的に
# 同じロックを取得すべきだが、そのまま無条件に取得すると、既にロックを保持している
# 親プロセスの子として起動された場合(通常のオーケストレーション経路)、親がロックを
# 解放するのを子が待ち、子の完了を親が待つという自己デッドロックに陥る。
# このため、親プロセスは子プロセス起動前にこの環境変数を立てて「ロックは既に
# 保持済みである」ことを子へ伝え、子側はこの値が真の場合は自身でのロック取得を
# スキップする(env=Noneのsubprocess.Popenは既定で親の環境変数をそのまま継承する
# ため、run_step()/ManagedProcess側の変更は不要)。
VRAM_LOCK_HELD_BY_PARENT_ENV = "VRAM_LOCK_HELD_BY_PARENT"

# nvidia-smiのPIDが「不要なPythonプロセス」かどうかの判定に使う部分一致キーワード。
# tools/safe_reset_infra.py の LOCK_CANDIDATE_NAME_KEYWORDS と同じ考え方: 無差別に
# システムプロセス全体を対象にせず、明らかに学習/推論用途のPythonプロセスだけに絞る
# (Ollama等の正当なGPU利用プロセスを誤って殺さないため)。
UNWANTED_PROCESS_NAME_KEYWORDS = ("python", "uvicorn")


def _decode_native_output(data: bytes) -> str:
    """ネイティブコマンドの出力バイト列を安全にデコードする。

    まずUTF-8(errors="strict")でのデコードを試みる。UTF-8として不正なバイト列
    だった場合のみ、locale.getpreferredencoding(False)(システムの現在のロケール設定)
    を用いた動的フォールバックデコードへ切り替える。
    """
    try:
        return data.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        fallback_encoding = locale.getpreferredencoding(False)
        return data.decode(fallback_encoding, errors="strict")


def run_native_command(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Windowsネイティブコマンド(nvidia-smi, taskkill等)との境界防衛(Anti-Corruption Layer)。"""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run(cmd, capture_output=True, env=env, **kwargs)
    return subprocess.CompletedProcess(
        args=result.args,
        returncode=result.returncode,
        stdout=_decode_native_output(result.stdout) if result.stdout else "",
        stderr=_decode_native_output(result.stderr) if result.stderr else "",
    )


def preflight_gpu_cleanup() -> list[int]:
    """nvidia-smiでVRAM占有中のPIDを取得し、自身以外の不要なPythonプロセスを
    taskkill /F で強制終了する。戻り値は実際に終了させたPIDのリスト。

    これは前回の異常終了で残ったゾンビプロセスの掃除であり、VRAM_LOCK_PATHによる
    健全なプロセス間調停とは独立した安全網(zombie descendant対策)である。
    """
    print("\n🧹 [Pre-flight] GPU Cleanup を実行します...")
    try:
        result = run_native_command(
            ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader"],
            timeout=15,
        )
    except FileNotFoundError:
        print("⚠️  nvidia-smiが見つかりません。GPUクリーンアップをスキップします。")
        return []
    except subprocess.TimeoutExpired:
        print(
            "⚠️  nvidia-smiがタイムアウトしました。GPUクリーンアップをスキップします。"
        )
        return []

    if result.returncode != 0:
        print(
            f"⚠️  nvidia-smiの実行に失敗しました(code={result.returncode})。"
            "GPUクリーンアップをスキップします。"
        )
        return []

    pids: list[int] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or "Insufficient Permissions" in line:
            continue
        try:
            pids.append(int(line.split(",")[0].strip()))
        except ValueError:
            continue

    self_pid = os.getpid()
    killed: list[int] = []
    for pid in pids:
        if pid == self_pid:
            continue
        try:
            name = (psutil.Process(pid).name() or "").lower()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if not any(keyword in name for keyword in UNWANTED_PROCESS_NAME_KEYWORDS):
            continue

        print(
            f"   🔥 VRAM占有中の不要なPythonプロセスを検知: PID={pid} ({name}) -> taskkill"
        )
        run_native_command(["taskkill", "/PID", str(pid), "/F"])
        killed.append(pid)

    if not killed:
        print("   ✅ 不要なプロセスは検出されませんでした。")
    return killed


def send_alert_webhook(message: str) -> None:
    """異常終了・定量評価ゲート不合格時にDiscord/Slack等のWebhookへ通知を送る。

    settings.alert_webhook_url が未設定(None)の場合、通知機能自体が無効化されて
    いるとみなし何もせずreturnする。

    【絶対制約】外部Webhookの障害(タイムアウト・DNS失敗・4xx/5xx等のあらゆる例外)は
    ここで必ず捕捉し、標準エラー出力へログを出すのみに留める。呼び出し元
    (run_step()のsys.exit(1)直前、各パイプラインのゲート判定後)はいずれもこの直後に
    VRAMロックの解放(finally節)や後続のFail-Fast終了処理を控えているため、
    ここで例外を伝播させるとその解放処理自体を巻き込んで壊してしまう。
    """
    if settings.alert_webhook_url is None:
        return

    url = settings.alert_webhook_url.get_secret_value()
    try:
        # Discord(content)/Slack(text)いずれの受信フォーマットにも解釈可能なよう、
        # 両方のキーを含めた汎用ペイロードを送る。
        httpx.post(url, json={"content": message, "text": message}, timeout=3.0)
    except Exception as e:  # noqa: BLE001 - Webhook障害は握って継続する(絶対制約)
        print(
            f"⚠️  [アラート通知] Webhook送信に失敗しました(無視して継続します): {e}",
            file=sys.stderr,
        )


def run_step(step_name: str, cmd: list[str], *, tolerate_failure: bool = False) -> bool:
    """1ステップをBASE_DIR起点で同期実行する。戻り値は成功したかどうか(bool)。

    tools/process_manager.ManagedProcess経由で起動することで、このステップ自身が
    正常終了した後でも、その子孫プロセスに生き残りが無いことをOSネイティブな
    機構(POSIXのプロセスグループ/WindowsのJob Object)で保証する(VRAMリークの
    原因となるゾンビ子孫プロセスの排除)。

    tolerate_failure=True の場合、このステップが失敗しても例外を送出せず、
    警告を出してFalseを返すのみとする(呼び出し元が「このステップは無くても
    後続を続行できる」と判断している場合のみ使う)。

    tolerate_failure=False でステップが異常終了した場合はドメイン固有例外を送出する
    (以前はここでsys.exit(1)により即座にプロセスを終了させていたが、これにより
    呼び出し元(各MLOpsパイプラインのmain())が実験管理DBへの記録
    (_record_experiment)やダッシュボード用静的JSONの更新(export_metrics)を
    一切実行できないまま死ぬサイレントな障害が生じていた。例外として送出することで、
    呼び出し元がtry/exceptで捕捉し、後始末を確実に行った上で終了できるようにする)。

    サブプロセスの終了コードで例外の型を分岐させる: returncode==125は
    tools/benchmark/run_benchmark.pyの_require_docker_or_die()が実際に送出する
    Docker/インフラ不在専用の終了コード(instructions/136、Docker CLI慣例に倣う)
    のため MLOpsInfrastructureError とする。それ以外の非0終了コードは、原則として
    サブプロセス自体のロジック的なクラッシュとみなし PipelineExecutionError とする。
    """
    print(f"\n🔍 [Step] {step_name} を実行します... ({' '.join(cmd)})")
    with process_manager.ManagedProcess(cmd, cwd=str(BASE_DIR)) as proc:
        stdout, stderr = proc.communicate()
        returncode = proc.returncode

    if stdout:
        print(stdout, end="")
    if stderr:
        print(stderr, end="")

    if returncode != 0:
        if tolerate_failure:
            print(
                f"⚠️  [継続] {step_name} が異常終了しましたが(code={returncode})、"
                "このステップは必須ではないため続行します。"
            )
            return False
        message = (
            f"🚨 [Fail-Fast] {step_name} が異常終了しました "
            f"(code={returncode})。パイプラインを停止します。"
        )
        print(message)
        send_alert_webhook(message)
        if returncode == 125:
            raise MLOpsInfrastructureError(message)
        raise PipelineExecutionError(message)

    print(f"✅ {step_name} が完了しました。")
    return True


class VramLockBusyError(Exception):
    """VRAMロックを他プロセス(アプリまたは別のMLOpsパイプライン)が保持中であることを示す。"""


def _try_acquire_once(lock: filelock.FileLock) -> None:
    try:
        lock.acquire(timeout=0)
    except filelock.Timeout as e:
        raise VramLockBusyError(
            f"VRAMロック({VRAM_LOCK_PATH})は他プロセスが保持中です。"
        ) from e


def _log_backoff_wait(retry_state: tenacity.RetryCallState) -> None:
    wait_sec = retry_state.next_action.sleep if retry_state.next_action else 0
    print(
        f"⏳ [VRAM排他制御] ロック取得待機中(試行{retry_state.attempt_number}回目)。"
        f"アプリまたは他のMLOpsパイプラインが稼働中の可能性があります。"
        f"{wait_sec:.1f}秒後に再試行します..."
    )


def acquire_vram_lock_with_backoff(
    max_wait_sec: int = 60,
) -> filelock.FileLock:
    """VRAMロックを、取得できるまで指数的バックオフでポーリング待機して取得する。

    MLOpsパイプラインはバッチジョブであり(対話的なユーザー応答を待たせているわけ
    ではない)、アプリ(即時応答が必要)や他のMLOpsパイプラインが使い終わるまで
    いつまでも待って良い。そのため上限回数を設けず、待機間隔だけを
    max_wait_sec 秒でクランプする(無限に間隔が伸びて実質止まったように見える
    事故を防ぐ)。

    戻り値は取得済みのロックオブジェクト。呼び出し元は使用後に必ず
    release() すること(finally節での解放を推奨)。
    """
    retrying = tenacity.Retrying(
        retry=tenacity.retry_if_exception_type(VramLockBusyError),
        wait=tenacity.wait_exponential(multiplier=2, min=2, max=max_wait_sec),
        before_sleep=_log_backoff_wait,
    )
    lock = filelock.FileLock(str(VRAM_LOCK_PATH))
    retrying(_try_acquire_once, lock)
    print(f"🔒 [VRAM排他制御] VRAMロックを取得しました({VRAM_LOCK_PATH})。")
    return lock
