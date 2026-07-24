# ... (既存コード)

import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union
from fastapi import APIRouter, Depends, HTTPException
from api.deps import verify_admin_token, handle_exceptions
from models.schemas import (
    AdminActionResponse,
    AdminDeployResponse,
    AuditLogListResponse,
    DlqActionRequest,
    DlqActionResponse,
    DlqListResponse,
    ErrorEnvelope,
    HumanActionRequest,
)
from nazokake_core.database import (
    async_discard_dlq_item,
    async_get_audit_logs,
    async_get_dlq_items,
    async_get_item,
    async_retry_dlq_item,
    async_upsert_item,
)

router = APIRouter()

# 【instructions/172: 1-Click Deploy】このファイル(backend/api/routers/admin.py)から
# 見て6階層上がスーパープロジェクトルート(main.pyの_PROJECT_ROOT = parents[3]と同じ
# 考え方だが、admin.pyはbackend/api/routers/配下のため階層がさらに2つ深い)。
_REPO_ROOT = Path(__file__).resolve().parents[5]
# 【instructions/187】ZIP圧縮(git archive)+gcloud compute scp(pscp.exe)による直接
# ファイル転送は、VM上の稼働ディレクトリから.git履歴を物理的に喪失させるアンチパターン
# としてSRE監査でRejectされた。tools/deploy/run_verification_server.ps1を、Bareリポジトリ
# (~/nazokake_apps.git)へのgit push→サーバー側deploy_pull.shの非同期キックによる
# 閉域GitOps(Pull型デプロイ)に全面刷新したtools/deploy/deploy_to_vm.ps1へ置き換えた。
_DEPLOY_SCRIPT_PATH = _REPO_ROOT / "tools" / "deploy" / "deploy_to_vm.ps1"
_DEPLOY_LOG_PATH = (
    _REPO_ROOT / "apps" / "evaluator" / "frontend" / "public" / "data" / "deploy.log"
)

# git status --porcelain(v1形式)の既知の「通常ファイルの変更」ステータスコード
# (2文字)。これに含まれないコード(サブモジュールの内部変更を示す小文字"m"を含む
# 状態等)は、意図しない自動コミットを避けるため安全側に倒してスキップする。
_SAFE_GIT_STATUS_CODES = {
    "M ", " M", "MM", "A ", "AM", " D", "D ", "R ", "RM", "C ", "AD",
}

_deploy_lock = threading.Lock()
_deploy_process: Optional[subprocess.Popen] = None

# モデルキー → ステータスフィールド名 / アクション → ステータス値
_MODEL_STATUS_FIELD = {"gemini": "gemini_status", "elyza": "elyza_status"}
_ACTION_TO_STATUS = {
    "golden": "golden",
    "approve": "approved",
    "reject": "rejected",
    "delete": "deleted",
}
# 「未評価でない（＝処理済み）」とみなすステータス集合
_RESOLVED_STATUSES = {"golden", "approved", "rejected", "deleted", "n/a"}


def _resolve_statuses(data: dict) -> tuple:
    """文書から (gemini_status, elyza_status) を決定する（レガシー互換の既定値込み）。

    新フィールド未設定の旧文書は is_golden_data / is_approved から既定値を補う。
    ELYZA 未生成（result_llmjp / nazokake_text_llmjp が無い）は 'n/a'（対象外）。
    """
    legacy_golden = bool(data.get("is_golden_data"))
    legacy_approved = bool(data.get("is_approved"))
    legacy = (
        "golden" if legacy_golden else ("approved" if legacy_approved else "pending")
    )
    g = data.get("result_gemini") or data.get("result") or {}
    has_gemini = bool(g.get("toku") or g.get("kokoro") or data.get("nazokake_text"))
    has_elyza = bool(
        (data.get("result_llmjp") or {}).get("toku")
        or (data.get("result_llmjp") or {}).get("kokoro")
        or data.get("nazokake_text_llmjp")
    )
    # データの無いモデルは 'n/a'（対象外＝処理済み扱い）。これにより単一モデル文書も resolved 判定が成立する。
    default_g = legacy if has_gemini else "n/a"
    default_e = legacy if has_elyza else "n/a"
    return data.get("gemini_status", default_g), data.get("elyza_status", default_e)


@router.post("/action", response_model=Union[AdminActionResponse, ErrorEnvelope])
@handle_exceptions
async def apply_human_action(
    req: HumanActionRequest,
    admin_token: dict = Depends(verify_admin_token),
):
    """管理者キュレーション: 対象なぞかけの gemini_status / elyza_status を更新する。

    Phase 4.11 の DPO抽出(Tier A/B)は、この gemini_status/elyza_status を
    golden/approved/rejected に更新する手段が無いまま(このエンドポイント自体が
    消失していたため)恒久的に0件抽出になっていた欠落を復旧するもの。
    """
    status_field = _MODEL_STATUS_FIELD[req.model]
    new_status = _ACTION_TO_STATUS[req.action]

    existing = await async_get_item(req.target_slug)
    if existing is None:
        raise HTTPException(status_code=404, detail="対象のなぞかけが見つかりません")

    await async_upsert_item({"doc_id": req.target_slug, status_field: new_status})
    updated = await async_get_item(req.target_slug)
    # 【絶対制約】sync_status(クラウド同期状態)はUI向けレスポンスに含めない。
    ui_updated = {k: v for k, v in updated.items() if k not in ("sync_status", "last_sync_error")}
    # APIの処理結果("success")とドキュメント自身の"status"フィールド(なぞかけの
    # 生成ステータス、例:"pending")はキー名が衝突するため、"data"キーの下へ
    # ネストして明確に分離する(旧実装は {"status": "success", **doc} のスプレッドで
    # ドキュメント側のstatusがsuccessを上書きしてしまうバグを内包していた)。
    return {"status": "success", "data": ui_updated}


@router.get("/dlq", response_model=Union[DlqListResponse, ErrorEnvelope])
@handle_exceptions
async def get_dlq_items(admin_token: dict = Depends(verify_admin_token)):
    """DLQ(sync_status=="fatal"、ポイズンピル隔離済み)の一覧を取得する。

    last_sync_error(隔離理由)とretry_countを含めて返す。
    """
    items = await async_get_dlq_items()
    return {"items": items}


@router.post("/dlq/action", response_model=Union[DlqActionResponse, ErrorEnvelope])
@handle_exceptions
async def apply_dlq_action(
    req: DlqActionRequest,
    admin_token: dict = Depends(verify_admin_token),
):
    """DLQに隔離されたアイテムへ「再試行」または「破棄」を適用する。

    対象が存在しない、または既にfatal(隔離中)でない場合は404。操作が成功した場合、
    直後に既存データを一切破壊しない追記専用の監査証跡(Audit Trail)を記録する。
    """
    reason_dict = {"requested_action": req.action}
    if req.action == "retry":
        found = await async_retry_dlq_item(req.doc_id, actor="admin", reason_dict=reason_dict)
    else:
        found = await async_discard_dlq_item(req.doc_id, actor="admin", reason_dict=reason_dict)

    if not found:
        raise HTTPException(status_code=404, detail="対象のDLQアイテムが見つかりません")

    return {"status": "success", "doc_id": req.doc_id, "action": req.action}


@router.get("/audit_logs", response_model=Union[AuditLogListResponse, ErrorEnvelope])
@handle_exceptions
async def get_audit_logs(admin_token: dict = Depends(verify_admin_token)):
    """監査証跡(audit_logs)を作成日時の降順で最大100件取得する。"""
    items = await async_get_audit_logs(limit=100)
    return {"items": items}


def _parse_git_status_targets(porcelain_output: str) -> list:
    """`git status --porcelain`(v1形式)の出力から、自動コミット対象として安全な
    パスのみを抽出する。

    - 追跡済みファイルの変更は、既知のステータスコード(_SAFE_GIT_STATUS_CODES)の
      場合のみ対象へ含める。
    - 未追跡ファイル(??)は tools/instructions/ 配下のみを安全対象として許可する
      (それ以外の未追跡ファイルを無差別に対象化することは絶対に行わない)。
    - サブモジュールの内部変更(" m"等、小文字を含む未知のコード)は安全側に倒して
      スキップする(意図しないサブモジュールポインタの自動コミットを避ける)。
    - リネーム("R  old -> new")は旧パス・新パスの両方を対象に含める。
    """
    targets: list = []
    for line in porcelain_output.splitlines():
        if not line:
            continue
        code = line[:2]
        rest = line[3:]
        if code.startswith("R") and " -> " in rest:
            paths = [p.strip().strip('"') for p in rest.split(" -> ", 1)]
        else:
            paths = [rest.strip().strip('"')]

        if code == "??":
            targets.extend(p for p in paths if p.startswith("tools/instructions/"))
            continue
        if code not in _SAFE_GIT_STATUS_CODES:
            continue
        targets.extend(paths)
    return targets


def _auto_commit_pending_changes(repo_root: Path) -> list:
    """作業ツリーに変更があれば、追跡済みファイルおよびtools/instructions/配下の
    安全な未追跡ファイルのみを明示的に指定して自動コミットする。

    【絶対制約】`git add .`は使わない。対象パスは必ず個別に列挙して`git add --`へ渡す
    (_parse_git_status_targets()が安全対象のみへ絞り込む)。変更が無い、または
    安全対象が1件も無い場合は何もせず空リストを返す。
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


def _is_deploy_running() -> bool:
    """現在バックグラウンドで実行中のデプロイがあるかを判定する(単一workerプロセス
    前提のインメモリ状態、run_api.ps1が--workers 1を強制する既存の運用規約と同じ
    前提に依拠する)。完了済みのプロセスは参照をクリアする。
    """
    global _deploy_process
    if _deploy_process is None:
        return False
    if _deploy_process.poll() is not None:
        _deploy_process = None
        return False
    return True


@router.post("/deploy", response_model=Union[AdminDeployResponse, ErrorEnvelope])
@handle_exceptions
async def trigger_deploy(admin_token: dict = Depends(verify_admin_token)):
    """検証サーバーへの閉域GitOps(Pull型)デプロイ(tools/deploy/deploy_to_vm.ps1)を
    バックグラウンドで起動する(instructions/172の骨格をinstructions/187のGitOps方式へ
    刷新、No-Toilの徹底)。

    実行前に作業ツリーの保留中の変更を自動コミットする(deploy_to_vm.ps1はgit pushで
    HEAD(直近のコミット)のみをVM上のBareリポジトリへ転送するため、コミットされて
    いない変更はこの手順が無ければ検証サーバーへ反映されない)。deploy_to_vm.ps1自体の
    標準出力/標準エラー出力(VM起動確認・SSH待機・push・非同期キックの通知まで)は
    deploy.logへ追記され、admin.jsがポーリングでこれをフロントエンドのターミナル風
    エリアへ表示する。VM側で実際に実行されるinfra/verification_env/deploy_pull.sh
    (git fetch/reset --hard→setup_verification_env.sh→docker compose up --build)は
    非同期キックのため、その進捗自体はこのdeploy.logには現れない
    (VM上の~/nazokake_apps_deploy_pull.logを参照、既知の限界)。

    【ローカル開発環境専用】このエンドポイントはWindows PowerShell/gcloud CLIの
    存在を前提とするため、デプロイ済みのCloud Run環境(frontend/を含まないコンテナ
    イメージ、apps/evaluator/Dockerfile参照)では機能しない。デプロイスクリプトが
    見つからない場合は明示的にエラーを返す(サイレントな失敗を避ける)。
    """
    global _deploy_process

    with _deploy_lock:
        if _is_deploy_running():
            raise HTTPException(
                status_code=409,
                detail="デプロイが既に進行中です。完了までお待ちください。",
            )
        if not _DEPLOY_SCRIPT_PATH.exists():
            raise HTTPException(
                status_code=500,
                detail=(
                    f"デプロイスクリプトが見つかりません: {_DEPLOY_SCRIPT_PATH}"
                    "(ローカル開発環境専用の機能です)"
                ),
            )
        if not (_REPO_ROOT / ".git").exists():
            raise HTTPException(
                status_code=500,
                detail=f"gitリポジトリが見つかりません: {_REPO_ROOT}",
            )

        committed = _auto_commit_pending_changes(_REPO_ROOT)

        _DEPLOY_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_DEPLOY_LOG_PATH, "a", encoding="utf-8") as log_file:
            log_file.write(
                f"\n=== [1-Click Deploy] 起動: {datetime.now(timezone.utc).isoformat()} ===\n"
            )
            log_file.flush()
            _deploy_process = subprocess.Popen(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(_DEPLOY_SCRIPT_PATH),
                ],
                cwd=str(_REPO_ROOT),
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )

    return {
        "status": "success",
        "message": "デプロイをバックグラウンドで開始しました。",
        "committed_files": committed,
        "log_path": "/data/deploy.log",
    }
