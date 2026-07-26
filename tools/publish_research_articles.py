"""
tools/publish_research_articles.py
====================================
instructions/233 Step1: 動作確認のため、tools/seed_research_data.py が投入した
下書き(is_published=False)の初期記事データを一括で公開(is_published=True)へ更新する。

使い方:
    uv run python tools/publish_research_articles.py
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from sqlalchemy import update  # noqa: E402

from nazokake_core.database import ResearchArticleORM, get_session  # noqa: E402


async def publish_all() -> None:
    now = datetime.now(timezone.utc).isoformat()
    async with get_session() as session:
        async with session.begin():
            result = await session.execute(
                update(ResearchArticleORM)
                .where(ResearchArticleORM.is_published.is_(False))
                .values(is_published=True, updated_at=now)
            )
    print(f"✅ {result.rowcount}件のResearchArticleをis_published=Trueへ更新しました。")


if __name__ == "__main__":
    asyncio.run(publish_all())
