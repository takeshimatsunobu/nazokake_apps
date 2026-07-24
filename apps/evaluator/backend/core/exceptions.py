import sys
from fastapi import Request
from fastapi.responses import JSONResponse
from loguru import logger

# Loguruのクラウドネイティブな初期化設定（標準エラー出力へ美しくフォーマット）
logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
)


async def global_exception_handler(request: Request, exc: Exception):
    logger.exception(f"未捕捉エラー発生 (エンドポイント: {request.url.path})")
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": 500,
                "message": "システム内部で予期せぬエラーが発生しました。",
                "details": str(exc),
            }
        },
    )
