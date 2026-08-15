"""
frontend/dev_server.py
=========================
ローカル開発用の素の静的サーバー(apps/evaluator/frontend/public/dev_server.py と
同じNo-Cache方針)。ES Modules(importmap)はfile://では動作しない(fetch/importが
CORSやMIMEタイプの制約でブロックされる)ため、このディレクトリで本スクリプトを
起動してhttp://経由でアクセスすること。

使い方:
    uv run python dev_server.py            # port 5500(既定、main.pyのCORS許可済み)
    uv run python dev_server.py 5501       # 別ポートを使う場合はmain.pyのCORS許可
                                            # 一覧(app.add_middleware(CORSMiddleware,...))
                                            # にも追記すること
"""
import http.server
import sys


class NoCacheHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5500
    print(f"🚀 persona_main_function frontend (No-Cache dev server) on http://127.0.0.1:{port}")
    http.server.test(HandlerClass=NoCacheHTTPRequestHandler, port=port)
