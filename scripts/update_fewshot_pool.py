"""Phase 4 Lv.1 バッチスクリプト: 高評価フィードバックによるFew-shotプール更新をAPI経由でトリガーする。

【Webhook方式への変更経緯】
旧バージョンはDBに直接接続し、このスクリプト自身のプロセス内で
refresh_fewshot_pool_from_feedback() を呼んでいたが、更新対象の
services.generation._FEWSHOT_POOL はプロセス内メモリであり、プロセス間で
共有されないため、稼働中のAPIサーバー(uvicorn main:app)には一切反映されなかった。
本バージョンはDBへの接続を一切行わず、稼働中のAPIサーバー自身に
POST /api/admin/feedbacks/refresh-fewshot を叩かせることで、
サーバーのプロセス内メモリを確実に更新する。

環境変数:
    API_BASE_URL : APIサーバーのベースURL(既定: http://127.0.0.1:7800)
    ADMIN_TOKEN  : 管理者権限のFirebase IDトークン(Authorization: Bearer <token>)

使い方(cron等から定期実行):
    python scripts/update_fewshot_pool.py
"""
import os
import sys

import httpx
from dotenv import load_dotenv


def main() -> None:
    load_dotenv()
    base_url = os.environ.get("API_BASE_URL", "http://127.0.0.1:7800")
    admin_token = os.environ.get("ADMIN_TOKEN", "")
    if not admin_token:
        print("🚨 環境変数 ADMIN_TOKEN が設定されていません。処理を中止します。")
        sys.exit(1)

    url = f"{base_url.rstrip('/')}/api/admin/feedbacks/refresh-fewshot"
    headers = {"Authorization": f"Bearer {admin_token}"}

    print(f"🔁 [Phase4 Lv.1] {url} を呼び出し、Few-shotプール更新をトリガーします...")
    try:
        response = httpx.post(url, headers=headers, timeout=60.0)
        response.raise_for_status()
        data = response.json()
        print(f"✅ Few-shotプール更新完了: {data.get('added', '不明')} 件の高評価エントリを追加しました。")
    except httpx.HTTPStatusError as e:
        print(f"🚨 APIエラー (status={e.response.status_code}): {e.response.text}")
        sys.exit(1)
    except Exception as e:
        print(f"🚨 リクエスト失敗: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
