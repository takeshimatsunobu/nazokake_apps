import asyncio
import re
import sys
import json
import csv
import argparse
import io
from pathlib import Path
import httpx
import pandas as pd
from markdownify import markdownify as md

# --- 設定 ---
OUTPUT_DIR = Path("data/research")
INDEX_FILE = OUTPUT_DIR / "index.json"
MAX_CONCURRENCY = 5  # 同時接続数


def csv_to_markdown(csv_text: str) -> str:
    """CSVテキストをMarkdownのテーブル形式に変換する"""
    reader = csv.reader(io.StringIO(csv_text.strip()))
    rows = list(reader)
    if not rows:
        return ""
    md_lines = [
        "| " + " | ".join(rows[0]) + " |",
        "|" + "|".join(["---"] * len(rows[0])) + "|",
    ]
    for row in rows[1:]:
        cleaned_row = [cell.replace("\n", "<br>") for cell in row]
        md_lines.append("| " + " | ".join(cleaned_row) + " |")
    return "\n".join(md_lines)


async def fetch_and_convert(client: httpx.AsyncClient, url: str) -> str:
    """URLの種類を判定し、適切なフォーマットで抽出・Markdown化する"""
    # 1. Google Docs の場合
    doc_match = re.search(r"/document/d/([a-zA-Z0-9-_]+)", url)
    if doc_match:
        export_url = f"https://docs.google.com/document/d/{doc_match.group(1)}/export?format=html"
        response = await client.get(export_url, follow_redirects=True)
        if response.status_code in (401, 403):
            raise PermissionError("アクセス権限がありません")
        response.raise_for_status()
        return md(response.text, heading_style="ATX")

    # 2. Google Sheets の場合
    sheet_match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url)
    if sheet_match:
        sheet_id = sheet_match.group(1)
        gid_match = re.search(r"gid=([0-9]+)", url)
        gid = gid_match.group(1) if gid_match else "0"
        export_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
        response = await client.get(export_url, follow_redirects=True)
        if response.status_code in (401, 403):
            raise PermissionError("アクセス権限がありません")
        response.raise_for_status()
        return csv_to_markdown(response.text)

    return ""


async def process_row(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    labels: list[str],
    urls: list[str],
    index_data: list,
):
    """1行分のデータを処理し、ローカルにファイルを保存する"""
    if not urls or not labels:
        return

    # ラベル解析（['なぞかけ研究所', '定義', '基本の形'] などの構造に対応）
    if len(labels) >= 3:
        category, sub_category = labels[0], labels[1]
        title = "_".join(labels[2:])
    elif len(labels) == 2:
        category, sub_category, title = labels[0], labels[1], labels[1]
    else:
        category, sub_category, title = "その他", "その他", labels[0]

    dir_path = (
        OUTPUT_DIR / sanitize_filename(category) / sanitize_filename(sub_category)
    )
    dir_path.mkdir(parents=True, exist_ok=True)

    async with sem:
        for idx, url in enumerate(urls):
            try:
                content = await fetch_and_convert(client, url)
                if not content:
                    continue

                suffix = f"_{idx + 1}" if len(urls) > 1 else ""
                file_name = f"{sanitize_filename(title)}{suffix}.md"
                file_path = dir_path / file_name

                file_path.write_text(content, encoding="utf-8")
                print(f"✅ Saved: {file_path.relative_to(OUTPUT_DIR)}")

                # フロント表示用のプレビュー（先頭数行）を生成
                lines = [
                    line.strip()
                    for line in content.split("\n")
                    if line.strip() and not line.startswith("#")
                ]
                preview = " ".join(lines[:3])[:100] + "..." if lines else ""

                index_data.append(
                    {
                        "category": category,
                        "sub_category": sub_category,
                        "title": title + suffix,
                        "file_path": str(file_path.relative_to(OUTPUT_DIR).as_posix()),
                        "preview": preview,
                    }
                )

            except Exception as e:
                print(f"❌ Failed to fetch {url}: {e}")


def sanitize_filename(name: str) -> str:
    name = str(name).replace("/", "／").replace("\\", "＼")
    return re.sub(r"[<>\*?\"|:]", "", name).strip()


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sheet-url",
        type=str,
        required=True,
        help="メイン一覧スプレッドシートの公開URL",
    )
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    index_data = []

    sheet_match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", args.sheet_url)
    if not sheet_match:
        print("[Fatal] 無効なスプレッドシートURLです。")
        sys.exit(1)

    gid_match = re.search(r"gid=([0-9]+)", args.sheet_url)
    gid = gid_match.group(1) if gid_match else "0"
    main_csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_match.group(1)}/export?format=csv&gid={gid}"

    print(">>> 📥 メイン一覧データの読み込み中...")
    df = pd.read_csv(main_csv_url, header=None)
    df = df.ffill()

    tasks = []
    sem = asyncio.Semaphore(MAX_CONCURRENCY)

    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0), follow_redirects=True) as client:
        for _, row in df.iterrows():
            labels, urls = [], []
            for cell in row.dropna():
                cell_str = str(cell).strip()
                # 結合されたURLを分離抽出
                found = re.findall(r"(https?://docs\.google\.com/[^\s]+)", cell_str)
                urls.extend(found)
                # URLを除去した残りをラベルとする
                label = re.sub(
                    r"https?://docs\.google\.com/[^\s]+", "", cell_str
                ).strip()
                if label:
                    labels.append(label)

            tasks.append(process_row(client, sem, labels, urls, index_data))

        await asyncio.gather(*tasks)

    INDEX_FILE.write_text(
        json.dumps(index_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n🚀 All Sync Completed! 記事数: {len(index_data)}")


if __name__ == "__main__":
    asyncio.run(main())
