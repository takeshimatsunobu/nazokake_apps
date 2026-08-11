// @ts-nocheck -- 未移行(段階的にJSDoc型付けを進める対象)
// frontend/public/main_admin.js
// admin.html 用のエントリーポイント。admin.js(トップレベルでFirebaseUI初期化・
// onAuthStateChanged監視を自己実行する)をimportし、クリックイベントの委譲ディスパッチを
// 一元的に設定する。

import {
    logout, deployToProduction, modelAction, retryDlqItem, discardDlqItem,
    submitInvite, approveAdminUser, handleUnlockAction,
    selectReviewStatus, confirmReviewStatus,
    openPersonaEditModal, savePersonaConfig, clearPersonaConfig,
} from "admin";
import { uiSwitchTab } from "ui/tabs";

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
    // 【Phase 0新設】5ペインのタブ切り替え(index.htmlのswitchTabと同じ規約、
    // ui/tabs.js::uiSwitchTab()をそのまま流用する)。
    switchTab: (el) => uiSwitchTab(el.dataset.arg),
    submitInvite: () => submitInvite(),
    approveAdminUser: (el) => approveAdminUser(el.dataset.uid),
    // 【Phase2新設】直談判レビュー(赦す/リセット/却下)。
    handleUnlockAction: (el) => handleUnlockAction(el.dataset.requestId, el.dataset.unlockAction),
    // 【Phase5/6新設】5段階評価(review_status)。旧toggleFewshotSelectionを置き換え。
    selectReviewStatus: (el) => selectReviewStatus(el.dataset.docId, el.dataset.reviewStatus),
    confirmReviewStatus: (el) => confirmReviewStatus(el.dataset.docId),
    // 【Phase4新設】ペルソナ管理(登録/上書き/クリア)。
    openPersonaEditModal: (el) => openPersonaEditModal(el.dataset.personaId),
    savePersonaConfig: () => savePersonaConfig(),
    clearPersonaConfig: (el) => clearPersonaConfig(el.dataset.personaId),
};

document.addEventListener('click', (e) => {
    const el = /** @type {HTMLElement} */ (/** @type {Element} */ (e.target).closest('[data-action]'));
    if (!el) return;
    const handler = CLICK_ACTIONS[el.dataset.action];
    if (!handler) return;
    e.preventDefault();
    handler(el);
});
