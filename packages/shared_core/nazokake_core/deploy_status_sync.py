"""
nazokake_core/deploy_status_sync.py
======================================
検証環境(GCP VM)のデプロイ/稼働状態を、SSH接続無しに確認するための
Firestore上の外部ステート(instructions/212)。

【背景】従来のDoD(Definition of Done)検証は、Agentがgcloud compute ssh経由で
検証VMへ直接ログインしコマンドを実行する(docker compose ps、SQLiteの行数確認等)
という強権的な設計だった。これはSRE監査により「自律型Agentの過剰権限」と
指摘され、代わりに検証VM側(infra/verification_env/deploy_pull.sh)がデプロイ
完了時に自身の状態をこのモジュール経由でFirestoreへ書き込み(outbound-onlyの
push、VMへの受信ポート開放は不要)、Agent/オペレーター側は read_deploy_status()
でFirestoreを読むだけで確認する(疎結合)。

firebase_adminの初期化・コレクション解決の慣習は、既存の一方向同期実装
(firestore_sync.py._ensure_firebase_app/_resolve_collection)と同一のパターンを
踏襲する。
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Literal

import firebase_admin
from firebase_admin import firestore

DEFAULT_COLLECTION = "deploy_status"

DeployStatus = Literal["deploying", "deployed", "failed"]


def _resolve_collection() -> str:
    """環境変数 FIRESTORE_DEPLOY_STATUS_COLLECTION で書き込み先コレクションを
    上書きできる(本番のdeploy_statusを汚さずにテスト用コレクションへ向けるため)。"""
    return os.environ.get("FIRESTORE_DEPLOY_STATUS_COLLECTION", DEFAULT_COLLECTION)


def _ensure_firebase_app() -> None:
    if not firebase_admin._apps:
        project_id = os.environ.get("GCP_PROJECT_ID") or None
        if project_id:
            firebase_admin.initialize_app(options={"projectId": project_id})
        else:
            firebase_admin.initialize_app()


def write_deploy_status(
    *,
    instance_name: str,
    commit_hash: str,
    status: DeployStatus,
    message: str,
    containers: dict[str, Any] | None = None,
) -> None:
    """検証VMのデプロイ状態をFirestoreへ書き込む(VM側、deploy_pull.shから呼ばれる)。

    ドキュメントIDはinstance_name(例: "nazokake-l4-vm")で固定し、常に最新状態への
    上書き(Upsert)とする。デプロイ履歴の追跡はGitのコミットログ自体がSSoTである
    ため、ここでは「直近1回の状態」のみを保持する。
    """
    _ensure_firebase_app()
    db = firestore.client()
    collection = _resolve_collection()

    payload = {
        "instance_name": instance_name,
        "commit_hash": commit_hash,
        "status": status,
        "message": message,
        "containers": containers or {},
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    db.collection(collection).document(instance_name).set(payload)


def read_deploy_status(instance_name: str) -> dict[str, Any] | None:
    """検証VMの最新デプロイ状態をFirestoreから読む(Agent/オペレーター側、SSH不要)。

    ドキュメントが存在しない場合(一度もデプロイが成功していない)はNoneを返す。
    """
    _ensure_firebase_app()
    db = firestore.client()
    collection = _resolve_collection()

    snapshot = db.collection(collection).document(instance_name).get()
    if not snapshot.exists:
        return None
    return snapshot.to_dict()
