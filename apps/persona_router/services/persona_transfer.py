"""
services/persona_transfer.py
===============================
persona_feature_plan_v3.md Phase6 §6.1: 機種変更用の引き継ぎコード。

匿名認証UIDはブラウザストレージに紐づくため、端末変更やデータ消去で失われる。
発行側で表示したコードを別端末で入力すると、narrator_personas.owner_uidが
新しいUIDへ移管される。

- A3K7-9PQR形式(英大文字+数字8桁、4桁ずつハイフン区切り)。誤読しやすい
  0/O/1/I/L は除外する。
- 24時間有効・1回使い切り。
- 発行・適用のいずれも Firestore トランザクションで原子化する
  (services/penalty.py::record_route_b と同じパターン)。
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from firebase_admin import firestore

TRANSFER_CODES_COLLECTION = "persona_transfer_codes"

_CODE_EXPIRY = timedelta(hours=24)
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # 0/O/1/I/L 除外
_CODE_SEGMENT_LENGTH = 4
_MAX_ISSUE_ATTEMPTS = 5


class TransferCodeError(Exception):
    """引き継ぎコードの発行・適用に失敗した場合の共通例外。

    呼び出し元(api/routers/personas.py)がHTTPExceptionへ変換する責務を持つ
    (このモジュール自身はFastAPIに依存しない)。
    """


def _generate_code() -> str:
    segment1 = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_SEGMENT_LENGTH))
    segment2 = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_SEGMENT_LENGTH))
    return f"{segment1}-{segment2}"


def issue_transfer_code(db, owner_uid: str) -> tuple[str, str]:
    """引き継ぎコードを発行する。戻り値は (code, expires_at_iso)。

    衝突(既存コードとの重複)は天文学的低確率だが、念のため既存ドキュメントが
    無いことを確認してから作成する(最大_MAX_ISSUE_ATTEMPTS回リトライ)。
    """
    now = datetime.now(timezone.utc)
    expires_at = now + _CODE_EXPIRY

    for _ in range(_MAX_ISSUE_ATTEMPTS):
        code = _generate_code()
        doc_ref = db.collection(TRANSFER_CODES_COLLECTION).document(code)
        if doc_ref.get().exists:
            continue
        doc_ref.set(
            {
                "code": code,
                "owner_uid": owner_uid,
                "created_at": now.isoformat(),
                "expires_at": expires_at.isoformat(),
                "used_at": None,
                "used_by_uid": None,
            }
        )
        return code, expires_at.isoformat()

    raise TransferCodeError("引き継ぎコードの発行に失敗しました(再試行してください)。")


def apply_transfer_code(db, code: str, new_owner_uid: str) -> int:
    """引き継ぎコードを適用し、旧owner_uid配下の全ペルソナをnew_owner_uidへ
    移管する。戻り値は移管件数。

    無効(存在しない/期限切れ/使用済み)な場合はTransferCodeErrorを送出する。
    組み込みペルソナ(is_builtin=true, owner_uid="SYSTEM")は移管対象に含めない
    (コード発行者が組み込みペルソナを所有することは無いはずだが、念のため
    明示的に除外する)。
    """
    code = code.strip().upper()
    doc_ref = db.collection(TRANSFER_CODES_COLLECTION).document(code)
    transaction = db.transaction()

    @firestore.transactional
    def _claim_code(transaction) -> str:
        snapshot = doc_ref.get(transaction=transaction)
        if not snapshot.exists:
            raise TransferCodeError("引き継ぎコードが見つかりません。")
        data = snapshot.to_dict() or {}

        if data.get("used_at"):
            raise TransferCodeError("この引き継ぎコードは既に使用されています。")

        expires_at_str = data.get("expires_at")
        try:
            expires_at = datetime.fromisoformat(expires_at_str) if expires_at_str else None
        except ValueError:
            expires_at = None
        if expires_at is None or expires_at <= datetime.now(timezone.utc):
            raise TransferCodeError("この引き継ぎコードは有効期限が切れています。")

        transaction.update(
            doc_ref,
            {
                "used_at": datetime.now(timezone.utc).isoformat(),
                "used_by_uid": new_owner_uid,
            },
        )
        return data["owner_uid"]

    old_owner_uid = _claim_code(transaction)

    from nazokake_core.narrator_personas import NARRATOR_PERSONAS_COLLECTION

    owned_docs = list(
        db.collection(NARRATOR_PERSONAS_COLLECTION)
        .where(filter=firestore.FieldFilter("owner_uid", "==", old_owner_uid))
        .stream()
    )
    transferred = 0
    for doc in owned_docs:
        data = doc.to_dict() or {}
        if data.get("is_builtin"):
            continue
        doc.reference.update(
            {"owner_uid": new_owner_uid, "updated_at": datetime.now(timezone.utc).isoformat()}
        )
        transferred += 1

    return transferred
