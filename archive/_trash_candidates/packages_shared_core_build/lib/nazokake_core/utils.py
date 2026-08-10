import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

def _normalize_for_sqlite(raw_timestamp: Any) -> datetime:
    """
    Firestore等から取得した時刻データをSQLiteのDateTimeカラム用に正規化する。
    過去に行われていた「強制的な文字列キャスト」は不等号比較のバグを生むため廃止された。
    """
    if raw_timestamp is None:
        return None
        
    try:
        # datetimeオブジェクトの場合はそのまま（タイムゾーンをUTCに統一するなどの処理を推奨）
        if isinstance(raw_timestamp, datetime):
            return raw_timestamp
            
        # ISO8601文字列等からの変換
        if isinstance(raw_timestamp, str):
            # Python 3.11+ の fromisoformat は末尾のZも解釈可能
            parsed = datetime.fromisoformat(raw_timestamp.replace('Z', '+00:00'))
            return parsed
            
        # Fail-Closed: 想定外の型（FirebaseのTimestampオブジェクトなど）は握り潰さず例外を投げる
        raise TypeError(f"サポートされていない時刻型です: {type(raw_timestamp)}")
        
    except Exception as e:
        logger.critical(f"時刻データの正規化に失敗しました。データ不整合を防ぐため処理を停止します: {e}")
        # 例外を握り潰して現在時刻やNoneで誤魔化す(Fail-Open)ことを固く禁じる
        raise ValueError(f"Invalid timestamp format: {raw_timestamp}") from e
