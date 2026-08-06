import logging
import traceback
from typing import Callable, Coroutine, Any

logger = logging.getLogger(__name__)

# DLQ(デッドレターキュー)の出力先パス
DLQ_PATH = "logs/dead_letter_queue.log"

def write_to_dlq(error_message: str, task_name: str):
    """
    サイレントフェイルを防ぐためのDLQ書き込み。
    機密情報(PII)のマスキング等は呼び出し元で担保すること。
    """
    try:
        with open(DLQ_PATH, "a", encoding="utf-8") as f:
            f.write(f"[DLQ] Task: {task_name} | Error: {error_message}\n")
    except Exception as e:
        # DLQ自体への書き込み失敗時は標準エラーへ確実に出力する
        logger.critical(f"DLQへの書き込みに失敗しました: {e}")

async def fail_closed_background_task(task_func: Callable[..., Coroutine[Any, Any, Any]], *args, **kwargs):
    """
    FastAPIのBackgroundTasksでエラーが握り潰されるのを防ぐFail-Closedラッパー。
    sync_once_safe等のバックグラウンド処理は必ずこのラッパーを経由して実行する。
    """
    task_name = task_func.__name__
    try:
        logger.info(f"バックグラウンドタスク '{task_name}' を開始します...")
        await task_func(*args, **kwargs)
        logger.info(f"バックグラウンドタスク '{task_name}' が正常に完了しました。")
    except Exception as e:
        error_details = traceback.format_exc()
        logger.error(f"バックグラウンドタスク '{task_name}' で例外が発生しました。DLQへ退避します: {e}")
        
        # 握り潰さずDLQへ出力し、監視システムが検知できるようにする
        write_to_dlq(error_details, task_name)
        
        # FastAPIのBackgroundTasks内でraiseしてもHTTPレスポンスには影響しないが、
        # サーバーのログ基盤(Datadog/Sentry等)にエラーを補足させるため例外を再送出する
        raise
