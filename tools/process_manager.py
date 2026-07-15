"""
tools/process_manager.py
===========================
クロスプラットフォーム対応の、プロセスツリーをアトミックに破棄するための管理レイヤー
(Epic 3)。

マルチプロセス運用(データ抽出・学習・評価等のサブプロセス起動)におけるVRAMリーク
(ゾンビ子孫プロセスによるGPUメモリ解放漏れ)をOSレベルで完全に排除するため、
サブプロセスの起動時点で「子孫プロセスをまとめて破棄できる箱」に入れておき、
終了時にはその箱ごと壊す。個々の子孫PIDをポーリングで追跡する不確実な方式
(旧: tools/train_unsloth.pyの--ppid自爆機構)はこの方式に置き換えられ廃止された。

- POSIX: subprocess.Popen(preexec_fn=os.setsid)で子プロセスを新しいプロセスグループの
  リーダーにし、os.killpg(pgid, signal)でグループ全体をアトミックに終了させる。
- Windows: ctypes.windll.kernel32でJob Objectを作成し、
  JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE属性を設定した上で子プロセスをアタッチする。
  Job Objectのハンドルを閉じると、アタッチされている全プロセスがOSによって
  アトミックに終了させられる。
  - 親プロセスが既に別のJob Object配下にある場合、AssignProcessToJobObjectが
    Access Denied(Error 5)で失敗することがある(Job Objectのネスト制限、絶対要件)。
    この場合は例外を安全に捕捉し、psutilで子孫プロセスツリーを再帰的に特定して
    個別終了させるフォールバック(taskkill /T相当)へGraceful Degradationする。

ctypes.windllのインポートはトップレベルではなく、Windows判定の内部(関数内)で
遅延インポートする(Linux実行環境でこのモジュールをimportしただけで
ImportError/AttributeErrorにならないようにするため)。
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys


class JobObjectAttachError(Exception):
    """Windows Job Objectの作成またはアタッチに失敗したことを表す(ネスト制限等)。"""


class ManagedProcess:
    """サブプロセスを起動し、その全ての子孫プロセスをアトミックに破棄できることを
    保証するコンテキストマネージャー。

    使い方:
        with ManagedProcess(cmd, cwd=...) as proc:
            stdout, stderr = proc.communicate()
        # ブロックを抜けると(正常終了・例外いずれの場合も)、まだ生き残っている
        # 子孫プロセスがあれば安全網としてまとめて終了させる。
    """

    def __init__(
        self,
        cmd: list[str],
        cwd: str | None = None,
        env: dict | None = None,
        text: bool = True,
        encoding: str | None = "utf-8",
        errors: str | None = "strict",
    ) -> None:
        self.cmd = cmd
        self.cwd = cwd
        self.env = env
        self.text = text
        self.encoding = encoding
        self.errors = errors
        self.popen: subprocess.Popen | None = None
        self._job_handle = None
        self._use_job_object = False

    # --- 起動 ---------------------------------------------------------

    def start(self) -> None:
        if os.name == "nt":
            self._start_windows()
        else:
            self._start_posix()

    def _popen_kwargs(self) -> dict:
        return {
            "cwd": self.cwd,
            "env": self.env,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": self.text,
            "encoding": self.encoding,
            "errors": self.errors,
        }

    def _start_posix(self) -> None:
        """新しいプロセスグループのリーダーとして起動する(POSIX)。"""
        self.popen = subprocess.Popen(
            self.cmd, preexec_fn=os.setsid, **self._popen_kwargs()
        )

    def _start_windows(self) -> None:
        """Job Objectを作成し、起動した子プロセスをアタッチする(Windows)。

        ネスト制限等でアタッチに失敗した場合は例外を外へ伝播させず、psutilベースの
        フォールバックへGraceful Degradationする(プロセス自体は既に起動済みのため
        続行可能)。
        """
        self.popen = subprocess.Popen(self.cmd, **self._popen_kwargs())

        job_handle = None
        try:
            job_handle = _create_kill_on_close_job_object()
            _assign_process_to_job_object(job_handle, self.popen.pid)
        except JobObjectAttachError as e:
            print(
                f"⚠️  [process_manager] Job Objectへのアタッチに失敗しました({e})。"
                "psutilベースのフォールバックへ切り替えます。",
                file=sys.stderr,
            )
            # create自体は成功していたがassignで失敗した場合、生成済みのJob Object
            # ハンドルをここで確実に閉じる(リークさせない)。
            if job_handle is not None:
                _close_handle(job_handle)
            self._use_job_object = False
            return

        self._job_handle = job_handle
        self._use_job_object = True

    # --- 待機 ---------------------------------------------------------

    def communicate(self, timeout: float | None = None):
        assert self.popen is not None
        return self.popen.communicate(timeout=timeout)

    def wait(self, timeout: float | None = None) -> int:
        assert self.popen is not None
        return self.popen.wait(timeout=timeout)

    @property
    def returncode(self) -> int | None:
        return self.popen.returncode if self.popen else None

    @property
    def pid(self) -> int:
        assert self.popen is not None
        return self.popen.pid

    # --- 破棄 ---------------------------------------------------------

    def terminate_tree(self) -> None:
        """プロセスツリーをアトミックに(まとめて)破棄する。

        既に正常終了している場合に呼んでも安全(冪等)であり、子孫の生き残りが
        無いことを確認する安全網として常に呼んで問題ない。
        """
        if self.popen is None:
            return

        if os.name == "nt":
            self._terminate_tree_windows()
        else:
            self._terminate_tree_posix()

    def _terminate_tree_posix(self) -> None:
        assert self.popen is not None
        try:
            pgid = os.getpgid(self.popen.pid)
        except ProcessLookupError:
            return  # 既に終了済み

        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            return

        try:
            self.popen.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def _terminate_tree_windows(self) -> None:
        if self._use_job_object and self._job_handle is not None:
            # Job Objectのハンドルを閉じると、KILL_ON_JOB_CLOSE属性により
            # アタッチされている全プロセスがOSによってアトミックに終了させられる。
            _close_handle(self._job_handle)
            self._job_handle = None
            return

        # Graceful Degradation: Job Objectが使えなかった場合、psutilで子孫
        # プロセスツリーを再帰的に特定して個別終了させる(taskkill /T相当)。
        assert self.popen is not None
        _kill_process_tree_with_psutil(self.popen.pid)

    # --- コンテキストマネージャー ----------------------------------------

    def __enter__(self) -> ManagedProcess:
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.terminate_tree()


def _kill_process_tree_with_psutil(pid: int) -> None:
    """psutilで対象PIDの子孫プロセスツリーを再帰的に特定し、個別に終了させる
    (taskkill /T相当のフォールバック)。
    """
    import psutil

    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return

    procs = parent.children(recursive=True)
    procs.append(parent)
    for proc in procs:
        try:
            proc.kill()
        except psutil.NoSuchProcess:
            pass
    psutil.wait_procs(procs, timeout=5)


# --- Windows Job Object (ctypes、遅延インポート) -----------------------------


def _create_kill_on_close_job_object():
    """JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE属性を持つJob Objectを作成し、ハンドルを返す。

    失敗時はJobObjectAttachErrorを送出する(呼び出し元でフォールバックへ移行させる)。
    """
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    job_object_extended_limit_information = 9
    job_object_limit_kill_on_job_close = 0x2000

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    job_handle = kernel32.CreateJobObjectW(None, None)
    if not job_handle:
        raise JobObjectAttachError(
            f"CreateJobObjectWに失敗しました: {ctypes.WinError()}"
        )

    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = job_object_limit_kill_on_job_close

    ok = kernel32.SetInformationJobObject(
        job_handle,
        job_object_extended_limit_information,
        ctypes.byref(info),
        ctypes.sizeof(info),
    )
    if not ok:
        err = ctypes.WinError()
        kernel32.CloseHandle(job_handle)
        raise JobObjectAttachError(f"SetInformationJobObjectに失敗しました: {err}")

    return job_handle


def _assign_process_to_job_object(job_handle, pid: int) -> None:
    """指定PIDのプロセスをJob Objectへアタッチする。

    親プロセスが既に別のJob Object配下にありネスト制限に引っかかる場合、
    AssignProcessToJobObjectがAccess Denied(Error 5)を返すことがある。この場合は
    JobObjectAttachErrorとして呼び出し元へ知らせ、psutilフォールバックへ
    Graceful Degradationできるようにする(システムをクラッシュさせない)。
    """
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.GetLastError.restype = wintypes.DWORD

    process_terminate = 0x0001
    process_set_quota = 0x0100
    error_access_denied = 5

    process_handle = kernel32.OpenProcess(
        process_terminate | process_set_quota, False, pid
    )
    if not process_handle:
        raise JobObjectAttachError(f"OpenProcessに失敗しました: {ctypes.WinError()}")

    try:
        ok = kernel32.AssignProcessToJobObject(job_handle, process_handle)
        if not ok:
            last_error = kernel32.GetLastError()
            if last_error == error_access_denied:
                raise JobObjectAttachError(
                    "AssignProcessToJobObjectがAccess Denied(Error 5)で失敗しました"
                    "(親プロセスが既に別のJob Object配下にあるネスト制限の可能性)。"
                )
            raise JobObjectAttachError(
                f"AssignProcessToJobObjectに失敗しました(Error {last_error})。"
            )
    finally:
        kernel32.CloseHandle(process_handle)


def _close_handle(handle) -> None:
    import ctypes

    ctypes.windll.kernel32.CloseHandle(handle)
