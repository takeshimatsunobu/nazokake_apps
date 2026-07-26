"""なぞかけ研究所(instructions/231, 233)ルーター。
GET /research/articles              : 公開済み記事の一覧(main_category > sub_category分類)
GET /research/articles/{article_id} : 公開済み記事の詳細(本文含む)

一般ユーザー向けの読み取り専用APIのため、admin系ルーターと異なり認証を要求しない
(Depends(verify_admin_token)等を付けない = 公開エンドポイント、feed.pyと同じ規約)。
"""

from typing import Union

from fastapi import APIRouter, HTTPException

from api.deps import handle_exceptions
from models.schemas import ErrorEnvelope, ResearchArticleDetail, ResearchArticleListResponse
from nazokake_core.database import (
    async_get_published_research_articles,
    async_get_research_article,
)

router = APIRouter()


@router.get(
    "/research/articles", response_model=Union[ResearchArticleListResponse, ErrorEnvelope]
)
@handle_exceptions
async def list_research_articles():
    articles = await async_get_published_research_articles()
    return {"articles": articles}


@router.get(
    "/research/articles/{article_id}",
    response_model=Union[ResearchArticleDetail, ErrorEnvelope],
)
@handle_exceptions
async def get_research_article(article_id: str):
    article = await async_get_research_article(article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="指定された記事が見つかりません")
    return article
