"""tools/deploy_poll_daemon.py
================================
ローカル常駐のデプロイ・ポーリングデーモン(instructions/203)。

【背景】以前は apps/evaluator/backend/api/routers/admin.py の POST /api/admin/deploy
が、ブラウザからのHTTPリクエストを起点に直接 subprocess.Popen(["powershell", ...,
deploy_to_vm.ps1]) を起動していた(instructions/172/187)。これは任意コード実行
(RCE)・特権エスケープのリスクとして、SRE監査で明確にRejectされた
(instructions/203)。

【新アーキテクチャ】admin.py の /deploy エンドポイントは、Firestoreの
system_configs/deploy_state ドキュメントへ {"status": "pending", ...} を書き込む
だけに縮退した(firestore.rulesでも system_configs は元々クライアント直読み書き
禁止のdeny-all対象であり、Admin SDK経由の正規処理としてこの用途に合致する)。

このデーモンはローカルマシン上に常駐し、そのドキュメントの変化を定期的に
ポーリング(Pull)で検知する。statusが"pending"であれば、Firestoreトランザクション
でアトミックに"running"へ遷移させて排他的にクレームした上で、実際のデプロイ
スクリプト(tools/deploy/deploy_to_vm.ps1)と、それに先立つ作業ツリーの自動コミット
(admin.pyから移設した_auto_commit_pending_changes、絶対制約: git add .は使わない)
をサブプロセスとして実行する。

このデーモン自身はネットワークからの入力を一切受け付けない
(ローカルのポーリングループのみが起動トリガー)。ブラウザ起点のHTTPリクエストが
ローカルマシンのプロセス起動に直接つながる経路は、この設計には存在しない。

使い方(ローカル開発機で、Windows PowerShell/gcloud CLIが使える状態で実行):
    python tools/deploy_poll_daemon.py
"""

from __future__ import annotations

import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import firebase_admin
from firebase_admin import firestore

BASE_DIR = Path(__file__).resolve().parent.parent
DEPLOY_SCRIPT_PATH = BASE_DIR / "tools" / "deploy" / "deploy_to_vm.ps1"
DEPLOY_LOG_PATH = (
    BASE_DIR / "apps" / "evaluator" / "frontend" / "public" / "data" / "deploy.log"
)

POLL_INTERVAL_SECONDS = 10

DEPLOY_STATE_COLLECTION = "system_configs"
DEPLOY_STATE_DOC = "deploy_state"

# git status --porcelain(v1形式)の既知の「通常ファイルの変更」ステータスコード
# (2文字)。これに含まれないコード(サブモジュールの内部変更を示す小文字"m"を含む
# 状態等)は、意図しない自動コミットを避けるため安全側に倒してスキップする。
# (apps/evaluator/backend/api/routers/admin.pyから移設。instructions/203で
# ネットワーク到達不能なこのデーモン側へ処理を寄せた。)
_SAFE_GIT_STATUS_CODES = {
    "M ", " M", "MM", "A ", "AM", " D", "D ", "R ", "RM", "C ", "AD",
}


def _log(message: str) -> None:
    print(f"[deploy_poll_daemon] {message}", file=sys.stderr, flush=True)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_firebase_app() -> None:
    if not firebase_admin._apps:
        firebase_admin.initialize_app(options={"projectId": "nazokakeapp-137e5"})


def _parse_git_status_targets(porcelain_output: str) -> list[str]:
    """`git status --porcelain`(v1形式)の出力から、自動コミット対象として安全な
    パスのみを抽出する(admin.pyから移設、ロジック無改変)。

    - 追跡済みファイルの変更は、既知のステータスコード(_SAFE_GIT_STATUS_CODES)の
      場合のみ対象へ含める。
    - 未追跡ファイル(??)は無条件でスキップする(意図しない任意ファイルの自動コミット
      を避けるfail-closed設計。以前はtools/instructions/配下のみ例外的に許可して
      いたが、フェーズ2でtools/instructions/をarchive/instructions_history/へ移設した
      ことで対象が恒久的に存在しなくなったため、その特例コード自体を撤去した)。
    - サブモジュールの内部変更(" m"等、小文字を含む未知のコード)は安全側に倒して
      スキップする(意図しないサブモジュールポインタの自動コミットを避ける)。
    - リネーム("R  old -> new")は旧パス・新パスの両方を対象に含める。
    """
    targets: list[str] = []
    for line in porcelain_output.splitlines():
        if not line:
            continue
        code = line[:2]
        rest = line[3:]
        if code.startswith("R") and " -> " in rest:
            paths = [p.strip().strip('"') for p in rest.split(" -> ", 1)]
        else:
            paths = [rest.strip().strip('"')]

        if code not in _SAFE_GIT_STATUS_CODES:
            continue
        targets.extend(paths)
    return targets


def _auto_commit_pending_changes(repo_root: Path) -> list[str]:
    """作業ツリーに追跡済みファイルの変更があれば、それらのみを明示的に指定して
    自動コミットする(admin.pyから移設)。未追跡ファイルはfail-closedで対象外。

    【絶対制約】`git add .`は使わない。対象パスは必ず個別に列挙して`git add --`へ渡す
    (_parse_git_status_targets()が安全対象のみへ絞り込む)。変更が無い、または
    安全対象が1件も無い場合は何もせず空リストを返す。このデーモンはローカル
    マシン上でのみ動作し、ネットワークからの入力を起点に呼ばれることはない。
    """
    status_result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=True,
    )
    targets = _parse_git_status_targets(status_result.stdout)
    if not targets:
        return []

    subprocess.run(["git", "add", "--", *targets], cwd=str(repo_root), check=True)
    subprocess.run(
        ["git", "commit", "-m", "chore: 1-Click Deployによる自動同期"],
        cwd=str(repo_root),
        check=True,
    )
    return targets


def _try_claim_deploy_request(db, doc_ref) -> bool:
    """Firestoreトランザクションでstatus=="pending"をアトミックに"running"へ遷移させる
    (nazokake_core/firestore_sync.pyの@firestore.transactionalパターンを流用)。

    複数の本デーモンインスタンスが同時に稼働していても、この単一トランザクションが
    「1つだけがクレームに成功する」ことを保証するため、二重デプロイは構造的に発生しない。
    """

    @firestore.transactional
    def _txn(transaction) -> bool:
        snapshot = doc_ref.get(transaction=transaction)
        if not snapshot.exists:
            return False
        data = snapshot.to_dict() or {}
        if data.get("status") != "pending":
            return False
        transaction.update(
            doc_ref,
            {"status": "running", "claimed_at": _now_iso()},
        )
        return True

    return _txn(db.transaction())


def _run_deploy(doc_ref) -> None:
    """クレーム済みのデプロイ要求を実際に実行する。

    成功・失敗いずれの場合もFirestoreのdeploy_stateドキュメントを最終状態
    ("success"/"failed")へ更新する(「running」のまま無限に取り残される状態を防ぐ)。
    """
    try:
        if not DEPLOY_SCRIPT_PATH.exists():
            raise RuntimeError(
                f"デプロイスクリプトが見つかりません: {DEPLOY_SCRIPT_PATH}"
                "(このデーモンはローカル開発機専用です)"
            )
        if not (BASE_DIR / ".git").exists():
            raise RuntimeError(f"gitリポジトリが見つかりません: {BASE_DIR}")

        # deploy_to_vm.ps1はgit pushでHEAD(直近のコミット)のみをVM上のBare
        # リポジトリへ転送するため、コミットされていない変更はこの手順が無ければ
        # 検証サーバーへ反映されない。
        committed = _auto_commit_pending_changes(BASE_DIR)

        DEPLOY_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(DEPLOY_LOG_PATH, "a", encoding="utf-8") as log_file:
            log_file.write(
                f"\n=== [Deploy Poll Daemon] 起動: {_now_iso()} "
                f"(auto-committed: {committed}) ===\n"
            )
            log_file.flush()
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(DEPLOY_SCRIPT_PATH),
                ],
                cwd=str(BASE_DIR),
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )

        if result.returncode != 0:
            raise RuntimeError(
                f"deploy_to_vm.ps1が非ゼロ終了しました(exit code {result.returncode})"
            )

        doc_ref.update({"status": "success", "completed_at": _now_iso(), "last_error": None})
        _log("デプロイが成功しました。")
    except Exception as exc:
        _log(f"デプロイに失敗しました: {type(exc).__name__}: {exc}")
        doc_ref.update(
            {"status": "failed", "completed_at": _now_iso(), "last_error": str(exc)}
        )


def main() -> None:
    _ensure_firebase_app()
    db = firestore.client()
    doc_ref = db.collection(DEPLOY_STATE_COLLECTION).document(DEPLOY_STATE_DOC)

    _log(f"デプロイ・ポーリングデーモンを起動しました(polling interval={POLL_INTERVAL_SECONDS}s)。")
    while True:
        try:
            if _try_claim_deploy_request(db, doc_ref):
                _log("デプロイ要求を検知・クレームしました。デプロイを実行します。")
                _run_deploy(doc_ref)
        except Exception as exc:
            # ポーリングサイクル自体の異常(Firestore接続エラー等)はデーモンを
            # 停止させず、次のサイクルで再試行する(instructions/003のsync_daemonと
            # 同じ「クラッシュしない常駐プロセス」の方針)。
            _log(f"ポーリングサイクルでエラーが発生しました: {type(exc).__name__}: {exc}")
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
