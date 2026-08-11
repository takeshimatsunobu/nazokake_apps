// @ts-nocheck -- 未移行(段階的にJSDoc型付けを進める対象。ServiceWorker専用グローバルのため)
//
// キルスイッチ版 Service Worker(完全初期化・自己破壊用)。
//
// 【ファクト調査の結論(このファイルを書き換える前提として記録)】
// - 以前このファイルは apps/evaluator/frontend/public/sw.js.disabled という名前で
//   無効化されていた(ブラウザからは/sw.js.disabledとしてしか取得できず、
//   /sw.jsへのリクエストは404になるため、既に登録済みのブラウザではブラウザの
//   自動更新チェックが失敗し続け、古いSWが居座り続ける状態だった)。
// - 無効化される前・後を含め、このSWは一度もCache Storage API(caches.open/
//   caches.put/caches.match)を使っていない(Network-Only + オフライン用の動的
//   レスポンス生成のみ)。したがって「このSW自身が作ったCache Storageエントリ」は
//   存在しない。それでも本ファイルはcaches.keys()で取得できる全キャッシュを
//   無条件に削除する(過去の別バージョンや、他の目的で書き込まれた可能性のある
//   キャッシュも含めて安全側に倒すため)。
// - registerを呼んでいたコードは apps/evaluator/frontend/public/main_index.js に
//   あったが、既にコメントアウトされ無効化されていた(該当箇所は本対応で削除し、
//   unregister()による強制解除ロジックへ一本化した。詳細はmain_index.js参照)。
//
// 【本ファイルの役割】
// このファイルを/sw.jsとして復活(sw.js.disabled → sw.js へリネーム)させたのは、
// ブラウザが定期的に行う既存Service Workerの自動更新チェック(ページ遷移のたびに
// 最大24時間に1回程度、既存登録のスクリプトURLをバイト比較する仕様)によって、
// まだ古いSWが有効なまま残っている端末にもこのキルスイッチが自然に配信され、
// インストール→アクティベート→全キャッシュ削除→自己登録解除、まで一気通貫で
// 実行されるようにするため。main_index.js側の即時unregister()と合わせた
// 二重の安全策(このSWのfetch中でない端末はunregister()で即解除、まだ古いSWが
// 生きている端末はこのキルスイッチが配信されて自壊する)。
//
// 更新時は必ずこのバージョン文字列を変更すること(ブラウザがバイト差分を検知して
// 更新サイクルを起動するトリガーになる)。
const SW_VERSION = 'KILL_SWITCH_v20260811a';

self.addEventListener('install', (event) => {
    // 待機(waiting)状態を経由せず即座にactivateへ進める。
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        Promise.all([
            // caches.keys()で取得できる全てのCache Storageエントリを無条件で削除する。
            caches.keys().then((keys) =>
                Promise.all(
                    keys.map((key) => {
                        console.log('🗑️ [SW Kill Switch] キャッシュを削除します:', key);
                        return caches.delete(key);
                    })
                )
            ),
            // 既に開いている全てのタブ/ウィンドウを即座にこのSW(キルスイッチ)の
            // 制御下に置く(次のfetchから確実にこのSWが介在する状態にしてから、
            // 直後に自己登録解除することで「古いSWの制御下から一度も抜けられない」
            // 事態を避ける)。
            self.clients.claim(),
        ]).then(() => {
            console.log('✅ [SW Kill Switch] 全キャッシュ削除・クライアント制御の掌握が完了しました。自己解除します。');
            // 役目を終えたら自分自身の登録を解除する(このSWを永続的に居座らせない)。
            return self.registration.unregister();
        })
    );
});

// 【重要】fetchイベントリスナーは意図的に一切登録しない。
// リスナー自体が存在しなければ、このSWはネットワークリクエストに一切介入しない
// (event.respondWith()を呼ばない空のリスナーを置くのではなく、リスナー自体を
// 削除することで、ブラウザのデフォルト挙動(SWを経由しない通常のfetch)に
// 完全に委ねる)。
