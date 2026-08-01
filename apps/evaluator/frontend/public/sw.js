// @ts-nocheck -- 未移行(段階的にJSDoc型付けを進める対象。ServiceWorker専用グローバルのため)
// キャッシュ地獄を防ぐための最小構成 (Network-Only + オフライン審査突破用動的レスポンス)
//
// 【instructions/295】このファイルはCache Storage API(caches.open/caches.match等)を
// 一切使用しない設計のため、旧バージョンのキャッシュパージ処理は該当なし(instructions/295
// Step2の「使用していなければスキップでよい」に該当)。代わりに、ブラウザがこのSW自体を
// 「変更された」と検知して更新サイクル(install→activate)を起動できるよう、このバージョン
// マーカーをバイト変更する。更新時は必ずこの値も更新すること(index.html/admin.htmlの
// import mapバージョンと合わせておくと追跡しやすい)。
const SW_VERSION = 'v20260802';
self.addEventListener('install', (event) => {
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil(clients.claim());
});

self.addEventListener('fetch', (event) => {
    event.respondWith(
        fetch(event.request).catch((error) => {
            // ネットワークエラー（オフライン）かつ、HTMLページ（navigate）の要求だった場合のみ介入
            if (event.request.mode === 'navigate') {
                // PWAインストール要件(HTTP 200 OK)をパスするための、ダミーHTMLをメモリ上で動的に生成して返す
                return new Response(
                    '<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>オフライン - なぞかけ道場</title></head><body style="text-align:center; padding:50px; font-family:sans-serif; background-color:#F9F6EA; color:#333;"><h2>現在オフラインです</h2><p>ネットワーク接続を確認して、再度お試しください。</p></body></html>',
                    {
                        status: 200,
                        headers: { 'Content-Type': 'text/html' }
                    }
                );
            }
            // API通信や画像取得のエラーには一切介入せず、そのまま投げる（サイレントバグ防止）
            throw error;
        })
    );
});
