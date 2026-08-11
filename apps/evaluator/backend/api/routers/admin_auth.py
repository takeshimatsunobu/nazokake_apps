"""api/routers/admin_auth.py
=============================
Phase 0: 完全招待制の管理者認証ワークフロー。

POST /invites          : 招待URL(トークン付き)を発行し、招待メールを送信する(管理者専用)。
POST /invites/redeem   : 招待トークンを検証し、admin_users を status="pending_approval" で
                          作成する。オーナーへ承認依頼メールを送信する(ログイン済みユーザー
                          なら誰でも呼べるが、招待メールと一致しないメールアドレスは弾く)。
POST /users/{uid}/approve : オーナーが承認待ちユーザーを承認する(オーナー専用)。
GET  /pending-admins    : 承認待ちユーザーの一覧(オーナー専用)。

【なぜ verify_admin_token ではなく verify_user_token を redeem に使うか】
verify_admin_token は admin_users.status=="approved" を要求するため、承認待ちの本人は
そもそもこれを通過できない(そういう人を承認待ちにするためのエンドポイントなので、当然
「まだ承認されていない」状態で呼べなければならない)。そのため redeem のみ、単に「有効な
Firebase IDトークンか」だけを見る verify_user_token を使う。
"""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from api.deps import get_db, handle_exceptions, verify_admin_token, verify_user_token
from models.schemas import (
    AdminApproveResponse,
    InviteCreateRequest,
    InviteCreateResponse,
    InviteRedeemRequest,
    InviteRedeemResponse,
    PendingAdminUser,
    PendingAdminUsersResponse,
)
from services.email import send_approval_request_email, send_invite_email

router = APIRouter()

ADMIN_INVITES_COLLECTION = "admin_invites"
ADMIN_USERS_COLLECTION = "admin_users"
INVITE_EXPIRY_DAYS = 7


def _owner_email() -> str:
    return os.environ.get("OWNER_EMAIL", "").strip().lower()


def _admin_frontend_base_url() -> str:
    """招待URLを組み立てる際のフロントエンド基点URL。環境変数 ADMIN_FRONTEND_URL で
    上書きできる(未設定時はFirebase Hostingの既定URLへフォールバック)。
    """
    return os.environ.get(
        "ADMIN_FRONTEND_URL", "https://nazokakeapp-137e5.web.app"
    ).rstrip("/")


@router.post("/invites", response_model=InviteCreateResponse)
@handle_exceptions
async def create_invite(
    req: InviteCreateRequest,
    background_tasks: BackgroundTasks,
    admin_token: dict = Depends(verify_admin_token),
    db=Depends(get_db),
):
    """招待URL(トークン付き)を発行し、招待メールをバックグラウンドで送信する。

    承認済み管理者であれば誰でも招待を発行できる(オーナー限定にしていないのは、
    「招待は複数の管理者が行えてよいが、承認はオーナーのみ行える」という要件の
    非対称性をそのまま反映するため)。
    """
    email = req.email.strip().lower()
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=INVITE_EXPIRY_DAYS)

    db.collection(ADMIN_INVITES_COLLECTION).document(token).set(
        {
            "token": token,
            "email": email,
            "invited_by": admin_token.get("uid"),
            "invited_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "used": False,
        }
    )

    invite_url = f"{_admin_frontend_base_url()}/admin.html?invite={token}"

    # メール送信はレスポンスを遅延させないよう BackgroundTasks へ委譲する
    # (smtplibの同期I/Oはstarletteが自動的にスレッドプールで実行するため、
    # イベントループはブロックされない)。
    background_tasks.add_task(send_invite_email, email, invite_url)

    return InviteCreateResponse(
        status="success",
        message=f"{email} 宛に招待メールを送信しました",
        invite_url=invite_url,
    )


@router.post("/invites/redeem", response_model=InviteRedeemResponse)
@handle_exceptions
async def redeem_invite(
    req: InviteRedeemRequest,
    background_tasks: BackgroundTasks,
    user_token: dict = Depends(verify_user_token),
    db=Depends(get_db),
):
    """招待トークンを検証し、admin_users を status="pending_approval" で作成する。"""
    invite_ref = db.collection(ADMIN_INVITES_COLLECTION).document(req.token)
    snapshot = invite_ref.get()
    if not snapshot.exists:
        raise HTTPException(status_code=404, detail="招待リンクが見つかりません")

    invite = snapshot.to_dict() or {}

    if invite.get("used"):
        raise HTTPException(status_code=410, detail="この招待リンクは既に使用されています")

    expires_at = datetime.fromisoformat(invite["expires_at"])
    if expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="この招待リンクは有効期限が切れています")

    user_email = (user_token.get("email") or "").strip().lower()
    if not user_email or user_email != invite.get("email"):
        raise HTTPException(
            status_code=403,
            detail="このリンクはあなた宛ではありません(招待されたメールアドレスでログインしてください)",
        )

    uid = user_token["uid"]
    now = datetime.now(timezone.utc).isoformat()

    db.collection(ADMIN_USERS_COLLECTION).document(uid).set(
        {
            "uid": uid,
            "email": user_email,
            "status": "pending_approval",
            "invited_by": invite.get("invited_by"),
            "requested_at": now,
            "approved_by": None,
            "approved_at": None,
        },
        merge=True,
    )

    # 招待トークンは1回限り(使い回し・URL転送による不正利用を防ぐ)。
    invite_ref.update({"used": True})

    owner_email = _owner_email()
    if owner_email:
        background_tasks.add_task(
            send_approval_request_email, owner_email, user_email, uid
        )

    return InviteRedeemResponse(
        status="pending_approval",
        message="ログインを確認しました。メイン管理者の承認をお待ちください。",
    )


@router.post("/users/{uid}/approve", response_model=AdminApproveResponse)
@handle_exceptions
async def approve_admin_user(
    uid: str,
    admin_token: dict = Depends(verify_admin_token),
    db=Depends(get_db),
):
    """承認待ちユーザーを承認する。メイン管理者(オーナー)のみ実行できる。"""
    requester_email = (admin_token.get("email") or "").strip().lower()
    owner_email = _owner_email()
    if not owner_email or requester_email != owner_email:
        raise HTTPException(
            status_code=403, detail="この操作はメイン管理者のみ実行できます"
        )

    user_ref = db.collection(ADMIN_USERS_COLLECTION).document(uid)
    snapshot = user_ref.get()
    if not snapshot.exists:
        raise HTTPException(status_code=404, detail="対象のユーザーが見つかりません")

    user_ref.update(
        {
            "status": "approved",
            "approved_by": admin_token.get("uid"),
            "approved_at": datetime.now(timezone.utc).isoformat(),
        }
    )

    return AdminApproveResponse(status="success", message="承認しました")


@router.get("/pending-admins", response_model=PendingAdminUsersResponse)
@handle_exceptions
async def list_pending_admins(
    admin_token: dict = Depends(verify_admin_token),
    db=Depends(get_db),
):
    """承認待ちユーザーの一覧。オーナーのみ閲覧できる(承認可否を判断する情報のため)。"""
    requester_email = (admin_token.get("email") or "").strip().lower()
    owner_email = _owner_email()
    if not owner_email or requester_email != owner_email:
        raise HTTPException(
            status_code=403, detail="この操作はメイン管理者のみ実行できます"
        )

    docs = (
        db.collection(ADMIN_USERS_COLLECTION)
        .where("status", "==", "pending_approval")
        .stream()
    )
    items = [
        PendingAdminUser(
            uid=d.id,
            email=(d.to_dict() or {}).get("email", ""),
            status="pending_approval",
            requested_at=(d.to_dict() or {}).get("requested_at"),
        )
        for d in docs
    ]
    return PendingAdminUsersResponse(items=items)
