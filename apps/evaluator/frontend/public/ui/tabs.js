// @ts-nocheck -- 未移行(段階的にJSDoc型付けを進める対象)
// frontend/public/ui/tabs.js
export function uiSwitchTab(tabId) {
    // 古いアクティブ状態をクリア
    document.querySelectorAll('.view-section').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));

    // 新しいタブをアクティブ化
    const targetView = document.getElementById('view-' + tabId);
    const targetTab = document.getElementById('tab-' + tabId);

    if (targetView) targetView.classList.add('active');
    if (targetTab) targetTab.classList.add('active');

    // App Shell: 切替時は中央スクロール領域を先頭へ戻す（ヘッダー/ボトムは固定）
    document.querySelector('main')?.scrollTo({ top: 0 });
}
