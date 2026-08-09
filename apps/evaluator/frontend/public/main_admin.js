// @ts-nocheck -- 未移行(段階的にJSDoc型付けを進める対象)
// frontend/public/main_admin.js
// admin.html 用のエントリーポイント。admin.js(トップレベルでFirebaseUI初期化・
// onAuthStateChanged監視を自己実行する)をimportし、クリックイベントの委譲ディスパッチを
// 一元的に設定する。

import { logout, deployToProduction, modelAction, retryDlqItem, discardDlqItem } from "admin";

// data-actionだけでなく、要素自身のdata-*属性(data-doc-id/data-model/
// data-model-action等)も渡す必要があるハンドラ(modelAction/retryDlqItem/
// discardDlqItem)があるため、CLICK_ACTIONSの各関数はクリックされた要素(el)を
// 受け取る統一シグネチャにする(引数不要なハンドラはelを無視するだけでよい)。
const CLICK_ACTIONS = {
    logout: () => logout(),
    deployToProduction: () => deployToProduction(),
    modelAction: (el) => modelAction(el.dataset.docId, el.dataset.model, el.dataset.modelAction),
    retryDlqItem: (el) => retryDlqItem(el.dataset.docId),
    discardDlqItem: (el) => discardDlqItem(el.dataset.docId),
};

document.addEventListener('click', (e) => {
    const el = /** @type {HTMLElement} */ (/** @type {Element} */ (e.target).closest('[data-action]'));
    if (!el) return;
    const handler = CLICK_ACTIONS[el.dataset.action];
    if (!handler) return;
    e.preventDefault();
    handler(el);
});
