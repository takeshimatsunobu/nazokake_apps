from http.server import BaseHTTPRequestHandler, HTTPServer

class RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{"message": "Dummy Server GET OK"}')
        print(f"\n[ダミーサーバー] GETリクエストを受信しました！ パス: {self.path}")

    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{"choices": [{"message": {"content": "\u30c0\u30df\u30fc\u306e\u56de\u7b54\u3067\u3059"}}]}')
        print(f"\n[ダミーサーバー] POSTリクエストを受信しました！ パス: {self.path}")
        print(f"ヘッダー: {self.headers}")
        print(f"ボディ: {post_data.decode('utf-8')}")

server_address = ('', 11434)
httpd = HTTPServer(server_address, RequestHandler)
print("監視中... (Cloud Run からの通信を待っています。ブラウザでなぞかけを生成してください)")
httpd.serve_forever()
