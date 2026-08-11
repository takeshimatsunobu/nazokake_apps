"""services/penalty.py
======================
UUIDベースの段階的ペナルティ(荒らし対策)と、ブロック中の「エンタメ化」応答。

【ファクトチェックの結論(重要)】既存の frontend/state.js は「匿名UUIDは
/v1/generateへ送る必要がない」という前提で書かれていたが、サーバー側でUUID単位の
ブロック判定を行うには、UUID自体がリクエストに含まれていなければ不可能。
そのため models/schemas.py::GenerateRoutedRequest に client_uuid フィールドを
追加した(frontend/state.js の appState.uid をそのまま送るだけで済む、既存の
localStorage生成UUIDを再利用する設計)。匿名性・認証基盤不要という既存方針は
維持している(単なる文字列送信であり、クリアされれば別人として扱われる=
スプーフィング耐性は低いが、軽量な匿名システムとして許容する)。

【段階】ルートB(異常入力のエンタメ化)をn回引くごとに重くなる一時退場:
  5回: 2日間 / 10回: 1週間 / 15回: 1ヶ月 / 20回以降: 1年(以後もこの上限で据え置き)
5の倍数に達した瞬間だけ新たなblocked_untilを設定する(6〜9回目等は追加ペナルティ
なしで生成を許可し続ける、という要件の解釈)。

【ブロック中の扱い】/v1/generateはStep1/Step2のLLM呼び出しを一切行わず、
定型の「充電期間」応答を即時返す(コスト面・レイテンシ面の両方で有利。荒らしに
対してLLM課金を発生させ続けない設計)。

【直談判(unlock_requests)との関係】このモジュールは自動解除を行わない。
ユーザーがブロック画面から送信した申し立ては unlock_requests コレクションへ
別途保存され(api/routers/unlock.py)、実際の解除(blocked_untilのクリア)は
運営が手動で行うことを想定する(自動解除ロジックは本フェーズのスコープ外)。
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from firebase_admin import firestore

PENALTIES_COLLECTION = "user_penalties"

# (route Bの累計回数がこの値に達した「段階」, 退場期間)
_TIERS: list[tuple[int, timedelta]] = [
    (5, timedelta(days=2)),
    (10, timedelta(weeks=1)),
    (15, timedelta(days=30)),
    (20, timedelta(days=365)),
]


def _tier_duration_for_count(route_b_count: int) -> timedelta | None:
    """route_b_countが新たに5の倍数へ到達した場合のみ、その段階の退場期間を返す。
    到達していなければNone(追加ペナルティなしでそのまま生成を許可する)。
    """
    if route_b_count <= 0 or route_b_count % 5 != 0:
        return None
    tier_index = min(route_b_count // 5, len(_TIERS)) - 1
    return _TIERS[tier_index][1]


@dataclass
class BlockStatus:
    blocked: bool
    blocked_until: str | None  # ISO8601(UTC)。blocked=Falseの場合はNone。


def check_block_status(db, client_uuid: str) -> BlockStatus:
    """現在ブロック中かどうかを判定する(Step1/Step2のLLM呼び出し前に必ず通す
    高速な事前チェック用。Firestoreの単一ドキュメント読み取りのみで完結する)。
    """
    snapshot = db.collection(PENALTIES_COLLECTION).document(client_uuid).get()
    if not snapshot.exists:
        return BlockStatus(blocked=False, blocked_until=None)

    data = snapshot.to_dict() or {}
    blocked_until_str = data.get("blocked_until")
    if not blocked_until_str:
        return BlockStatus(blocked=False, blocked_until=None)

    blocked_until = datetime.fromisoformat(blocked_until_str)
    if blocked_until <= datetime.now(timezone.utc):
        return BlockStatus(blocked=False, blocked_until=None)

    return BlockStatus(blocked=True, blocked_until=blocked_until_str)


def record_route_b(db, client_uuid: str) -> BlockStatus:
    """ルートB(異常入力のエンタメ化)が発生した際に呼ぶ。累計回数を+1し、
    新たな段階に到達していればblocked_untilを設定する。

    Firestoreトランザクションでread-modify-writeを原子化し、同時に届いた
    複数リクエストによる二重カウント(レースコンディション)を防ぐ。
    """
    doc_ref = db.collection(PENALTIES_COLLECTION).document(client_uuid)
    transaction = db.transaction()

    @firestore.transactional
    def _run(transaction) -> BlockStatus:
        snapshot = doc_ref.get(transaction=transaction)
        data = snapshot.to_dict() if snapshot.exists else {}
        new_count = int(data.get("route_b_count", 0)) + 1
        now = datetime.now(timezone.utc)

        payload: dict = {
            "route_b_count": new_count,
            "updated_at": now.isoformat(),
        }

        duration = _tier_duration_for_count(new_count)
        if duration is not None:
            blocked_until_dt = now + duration
            payload["blocked_until"] = blocked_until_dt.isoformat()
            status = BlockStatus(blocked=True, blocked_until=payload["blocked_until"])
        else:
            # 新たな段階に未到達。既存のblocked_untilがまだ有効な場合に備え、
            # 現在値をそのまま維持する(誤って消さない。ここでは書き換えない)。
            existing_blocked_until = data.get("blocked_until")
            status = BlockStatus(blocked=False, blocked_until=existing_blocked_until)

        transaction.set(doc_ref, payload, merge=True)
        return status

    return _run(transaction)


# ------------------------------------------------------------
# ブロック中の「エンタメ化」応答(定型文・LLM呼び出しなし)
# ------------------------------------------------------------

# 否定的な語彙(禁止・ブロック等)を避け、「充電期間」として前向きに表現する。
_CHARGE_KOKORO_VARIANTS = [
    "今は次の一撃に向けて、じっくり英気を養っている真っ最中なのです",
    "あまりにキレが良すぎたので、少し充電させていただいております",
    "楽屋で次のネタを仕込み中、もうしばらくお待ちを",
    "才能がスパークしすぎたクールダウン期間、なにとぞご容赦を",
]


def _format_remaining(blocked_until_str: str) -> str:
    blocked_until = datetime.fromisoformat(blocked_until_str)
    remaining = blocked_until - datetime.now(timezone.utc)
    if remaining.total_seconds() <= 0:
        return "まもなく"
    days = remaining.days
    hours = remaining.seconds // 3600
    if days >= 1:
        return f"あと{days}日{hours}時間ほど"
    minutes = (remaining.seconds % 3600) // 60
    if hours >= 1:
        return f"あと{hours}時間{minutes}分ほど"
    return f"あと{max(minutes, 1)}分ほど"


def build_blocked_response(odai: str, blocked_until_str: str) -> tuple[str, str, str]:
    """ブロック中に返す「充電期間」応答(toku/kokoro/nazokake_text)を組み立てる。

    LLMを一切呼ばない(荒らしに対してAPI課金を発生させ続けない設計)。
    否定的な語彙を使わず、あくまでエンタメとして「充電期間」を演出する。
    """
    remaining_text = _format_remaining(blocked_until_str)
    toku = "ユーモアの充電期間に入った名人"
    kokoro = f"{random.choice(_CHARGE_KOKORO_VARIANTS)}({remaining_text}で復帰予定)"
    nazokake_text = f"「{odai}」とかけて、「{toku}」と解く。\nその心は、{kokoro}。"
    return toku, kokoro, nazokake_text
