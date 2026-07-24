// @ts-nocheck -- 未移行(段階的にJSDoc型付けを進める対象)
// frontend/public/main_admin.js
// admin.html 用のエントリーポイント。admin.js(トップレベルでFirebaseUI初期化・
// onAuthStateChanged監視を自己実行する)をimportし、クリックイベントの委譲ディスパッチを
// 一元的に設定する。

import { logout, deployToProduction } from "admin";

const CLICK_ACTIONS = {
    logout: () => logout(),
    deployToProduction: () => deployToProduction(),
};

document.addEventListener('click', (e) => {
    const el = /** @type {Element} */ (e.target).closest('[data-action]');
    if (!el) return;
    const handler = CLICK_ACTIONS[/** @type {HTMLElement} */ (el).dataset.action];
    if (!handler) return;
    e.preventDefault();
    handler();
});
