// @ts-nocheck -- 未移行(段階的にJSDoc型付けを進める対象)
// frontend/public/main_index.js
// index.html 用のエントリーポイント。app.js(Controller)と各ui/*.jsモジュールをimportし、
// クリック/入力イベントの委譲ディスパッチ、フォーム初期化、Service Worker登録、
// ヘルスチェックウォームアップの初期化順序をここで一元的にオーケストレーションする。
//
// app.js を単にimportするだけで、その内部の自己実行コード(匿名認証初期化・ディープリンク
// 処理・研究データロード・ページ来訪ログ)がモジュール評価時に実行される(従来の
// <script type="module" src="app.js">読み込みと同じ副作用タイミング)。

import {
    switchTab, startGeneration, submitFeedback, shareTextResult, switchBoardCategory,
    submitBoardPost, submitUserEvaluation, submitHumanRiddle, loadPersonaOptions,
} from "app";
import { API_BASE } from "config";
import { uiInitForm } from "ui/form";
import { setFeedbackRating } from "ui/feedback";
import { uiShowReplyForm, uiHideReplyForm } from "ui/board";
import { setFeedRating } from "ui/feed";
import {
    setGenRating, setGenComment, submitGenEvaluation, uiResetGenerator,
    setTemperatureDescription, initTemperatureDescription,
} from "ui/result";

// action名(data-action属性の値)の完全一致キーで実関数へディスパッチする。
// 旧実装のactionStr.includes(...)という部分文字列マッチは、意図しない誤爆
// (例: 'submitFeedback'という文字列が別のaction名の部分文字列になる等)の
// リスクを構造的に持っていたため、厳密な完全一致に置き換えて堅牢化する。
const CLICK_ACTIONS = {
    switchTab: (ds) => switchTab(ds.arg),
    startGeneration: () => startGeneration(),
    shareTextResult: (ds) => shareTextResult(ds.arg),
    setFeedbackRating: (ds) => setFeedbackRating(parseInt(ds.arg, 10)),
    submitFeedback: () => submitFeedback(),
    switchBoardCategory: (ds) => switchBoardCategory(ds.arg),
    submitBoardPost: (ds) => submitBoardPost(ds.parentId || null),
    setFeedRating: (ds) => setFeedRating(ds.docId, Number(ds.score)),
    submitUserEvaluation: (ds) => submitUserEvaluation(ds.docId),
    uiShowReplyForm: (ds) => uiShowReplyForm(ds.postId),
    uiHideReplyForm: (ds) => uiHideReplyForm(ds.postId),
    setGenRating: (ds) => setGenRating(ds.model, Number(ds.score)),
    submitGenEvaluation: (ds) => submitGenEvaluation(ds.model),
    uiResetGenerator: () => uiResetGenerator(),
};

const INPUT_ACTIONS = {
    setGenComment: (ds, value) => setGenComment(ds.model, value),
    setTemperatureDescription: (ds, value) => setTemperatureDescription(value),
};

document.addEventListener('click', (e) => {
    const el = /** @type {Element} */ (e.target).closest('[data-action]');
    if (!el) return;
    const handler = CLICK_ACTIONS[/** @type {HTMLElement} */ (el).dataset.action];
    if (!handler) return;
    e.preventDefault();
    handler(/** @type {HTMLElement} */ (el).dataset);
});

document.addEventListener('input', (e) => {
    const el = /** @type {Element} */ (e.target).closest('[data-oninput-action]');
    if (!el) return;
    const handler = INPUT_ACTIONS[/** @type {HTMLElement} */ (el).dataset.oninputAction];
    if (!handler) return;
    handler(/** @type {HTMLElement} */ (el).dataset, /** @type {HTMLInputElement} */ (e.target).value);
});

document.addEventListener('DOMContentLoaded', () => {
    // 自作鑑定フォームを初期化。UI制御は ui/form.js、API通信は submitHumanRiddle を注入。
    uiInitForm(submitHumanRiddle);
    // 「キャラの暴走度」スライダーの初期値(既定0.6)に対応する一言解説を表示する。
    initTemperatureDescription();
    // 【2026-08-16改修】マイペルソナ/みんなのペルソナ/＋新規作成をペルソナ
    // ドロップダウンへ動的追加する(ビルトイン10体は既にHTML側に静的表示済み)。
    loadPersonaOptions();
});

// 【Service Worker キルスイッチ】このアプリはService Workerによるキャッシュ機能を
// 意図的に使わない方針のため、通常のregister()は行わない(そのロジックは
// unregister()を強制実行するロジックへ書き換え済み。以前ここにあった
// register('sw.js')の呼び出し(コメントアウト状態で放置されていた死んだコード)は
// 削除した)。
//
// 【なぜunregister()だけでなくsw.js自体もキルスイッチ版として復活させたか】
// 以前このオリジンへアクセス済みのブラウザには、過去のService Worker登録が
// 残ったままになっている場合がある(register()を呼ばなくなっただけでは既存の
// 登録は自動解除されない)。古いSWがfetchをインターセプトし続け、バックエンド
// 修正後も「現在オフラインです」等の古いキャッシュ画面から抜け出せない実害が
// 確認された(ユーザーからの報告)。そこで二重の安全策にしている:
//   1) このページを開いた時点で残存登録があれば、以下のコードが即座にunregister()する。
//   2) 万一(1)より前にブラウザの裏側でSWの定期更新チェックが走った場合でも、
//      apps/evaluator/frontend/public/sw.js は「インストールされたら即座に全
//      Cache Storageを削除して自己解除するキルスイッチ」に書き換え済みのため、
//      古いSWが生きていたブラウザ側でも最終的に自壊する(sw.js側のコメント参照)。
// 登録が無ければ何もしない(no-op)ため、通常時のコストは無視できる。
if ('serviceWorker' in navigator) {
    navigator.serviceWorker.getRegistrations().then(regs => {
        regs.forEach(reg => {
            reg.unregister();
            console.log('🧹 [SW Cleanup] 残存していたService Worker登録を解除しました:', reg.scope);
        });
    }).catch(() => {});
}

// バックエンドの0円コールドスタート対策ウォームアップ(旧index.html末尾のインラインscriptから移設、
// ロジックは無改変)。
window.addEventListener('load', () => {
    setTimeout(() => {
        // config.js の API_BASE(SSoT)を使う。以前はここで別途ローカルポートをハードコード
        // 複製しており、config.jsとの食い違い(構成ドリフト)でERR_CONNECTION_REFUSEDを
        // 起こしたことがあるため、二重管理をやめて一本化する。
        const warmupUrl = `${API_BASE}/health`;

        console.log("⚙️ [Warmup] " + warmupUrl + " へフェッチを送信し、サーバーを安全に起動します...");

        fetch(warmupUrl)
            .then(res => res.json())
            .then(data => console.log("⚙️ [Warmup] 事前起動（0円ウォームアップ）に成功しました：", data))
            .catch(err => console.warn("⚙️ [Warmup] ウォームアップ通信でエラーが発生しましたが、動作には影響ありません。", err));
    }, 2000);
});
