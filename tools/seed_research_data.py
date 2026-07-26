"""
tools/seed_research_data.py
=============================
instructions/231: 「なぞかけ研究所」記事データ基盤への初期データ投入。

タイトル一覧(main_category > sub_category > title)をResearchArticleとして
ローカルSQLite(research_articlesテーブル)へ一括Upsertする。本文(content)は
未執筆のため一律プレースホルダーとし、is_published=False(下書き扱い)で投入する。

使い方:
    uv run python tools/seed_research_data.py
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from nazokake_core.database import ResearchArticleORM, get_session  # noqa: E402
from nazokake_core.schemas import ResearchArticle  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent.parent

CONTENT_PLACEHOLDER = "執筆中..."
MAIN_CATEGORY = "なぞかけ研究所"

# (sub_category, title) のタプル一覧。instructions/231の[データ一覧]をそのまま転記する。
ARTICLES: list[tuple[str, str]] = [
    ("新しいなぞかけの定義（仮）", "📖 辞書・事典別アプローチ比較一覧"),
    ("なぞかけ文化の促進", "📜 なぞかけ進化論：歴史のプロと紐解く推論と歴史"),
    ("なぞかけ文化の促進", "なぞかけの歴史（漫談風）"),
    ("なぞかけ基礎研究", "なぞかけと生理現象"),
    ("なぞかけ基礎研究", "なぞかけその他の研究の現状"),
    ("なぞかけ基礎研究", "２０世紀以前のなぞかけ調査"),
    ("なぞかけ基礎研究", "なぞかけ名人とそのうんちく"),
    ("なぞかけ基礎研究", "なぞかけに類似する文化"),
    ("なぞかけ比較文化論", "日本の類似文化"),
    ("なぞかけ比較文化論", "海外の言葉遊びの研究手法"),
    ("なぞかけ比較文化論", "第1象限：秩序と伝達の言語文化（協調 × 直接的・実用的）"),
    ("なぞかけ比較文化論", "第2象限：共感と審美の言語文化（協調 × 間接的・遊戯的）"),
    ("なぞかけ比較文化論", "第3象限：論争と闘争の言語文化（対立 × 直接的・実用的）"),
    ("なぞかけ比較文化論", "第4象限：対立の遊戯的昇華（各国のなぞかけ的文化）（対立 × 間接的・遊戯的）"),
    ("なぞかけ生成に関する分析", "現在このアプリで使用している生成評価の仕組み"),
    ("なぞかけ生成に関する分析", "新たなアルゴリズムのたね"),
    ("なぞかけ生成に関する分析", "生成AI（LLM）の基礎知識"),
    ("なぞかけ生成に関する分析", "機械学習の基礎知識"),
    ("なぞかけ評価に関する分析", "新たなロジックのたね"),
]


def _build_articles() -> list[ResearchArticle]:
    """ARTICLES一覧をPydanticでバリデーションしつつResearchArticleへ変換する。

    投入前にPydanticの必須フィールド制約(min_length等)を通すことで、
    データ一覧側のtypo(空文字など)を検知した状態でDBへ書き込む。
    """
    now = datetime.now(timezone.utc)
    articles = []
    for sub_category, title in ARTICLES:
        articles.append(
            ResearchArticle(
                article_id=str(uuid.uuid4()),
                main_category=MAIN_CATEGORY,
                sub_category=sub_category,
                title=title,
                content=CONTENT_PLACEHOLDER,
                created_at=now,
                updated_at=now,
                is_published=False,
            )
        )
    return articles


async def seed() -> None:
    articles = _build_articles()
    async with get_session() as session:
        async with session.begin():
            for article in articles:
                row = article.model_dump(mode="json")
                session.add(ResearchArticleORM(**row))

    print(f"✅ {len(articles)}件のResearchArticleをresearch_articlesテーブルへ投入しました。")


if __name__ == "__main__":
    asyncio.run(seed())
