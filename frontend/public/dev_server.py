import http.server
import sys

class NoCacheHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        # 強制的にキャッシュを無効化する防弾ヘッダーを付与
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 7300
    print(f"🚀 No-Cache Development Server running on port {port}...")
    http.server.test(HandlerClass=NoCacheHTTPRequestHandler, port=port)