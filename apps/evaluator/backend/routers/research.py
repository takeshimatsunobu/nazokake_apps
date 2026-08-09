import json
import hashlib
from pathlib import Path
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/research", tags=["research"])

# CWD依存を排除。リポジトリルート(nazokake_apps)からの絶対パスを特定
BASE_DIR = Path(__file__).resolve().parents[4]
RESEARCH_DIR = BASE_DIR / "data" / "research"

def _make_slug(path_str: str) -> str:
    """ファイルパスからURLセーフで一意なID(slug)を生成"""
    return hashlib.md5(path_str.encode()).hexdigest()

def _load_index() -> list[dict]:
    index_file = RESEARCH_DIR / "index.json"
    if not index_file.exists():
        return []
    return json.loads(index_file.read_text(encoding="utf-8"))

@router.get("/articles")
def list_articles():
    items = _load_index()
    for item in items:
        item["slug"] = _make_slug(item["file_path"])
    return {"articles": items}

@router.get("/articles/{slug}")
def get_article(slug: str):
    items = _load_index()
    target_item = next((item for item in items if _make_slug(item["file_path"]) == slug), None)
    
    if not target_item:
        raise HTTPException(status_code=404, detail="article not found")

    md_file = (RESEARCH_DIR / target_item["file_path"]).resolve()
    
    # パストラバーサル防止
    if not md_file.is_relative_to(RESEARCH_DIR.resolve()) or not md_file.exists():
        raise HTTPException(status_code=404, detail="content not found")

    return {"title": target_item["title"], "content": md_file.read_text(encoding="utf-8")}
