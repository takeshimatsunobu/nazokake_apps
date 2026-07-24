// @ts-nocheck -- 未移行(段階的にJSDoc型付けを進める対象)
// frontend/public/ui/toast.js
export function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    const isWarning = (type === 'warning');
    const bgClass = isWarning ? 'bg-[#902A19]' : 'bg-[#C5B358]';
    const icon = isWarning ? '⚠️' : '✨';
    const textColor = isWarning ? 'text-white' : 'text-gray-900';

    toast.className = `${bgClass} text-white px-6 py-3 rounded-full shadow-lg transform transition-all duration-300 -translate-y-10 opacity-0 flex items-center gap-2 font-bold text-sm pointer-events-auto z-50`;
    toast.innerHTML = `<span>${icon}</span><span class="${textColor}">${message}</span>`;

    container.appendChild(toast);
    requestAnimationFrame(() => toast.classList.remove('-translate-y-10', 'opacity-0'));

    setTimeout(() => {
        toast.classList.add('opacity-0', '-translate-y-2');
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// システムエラー通知（app.js から移設）。通知系を本ファイルに集約する。
// alert で致命的エラーを知らせつつ、ローディング表示の解除と生成ボタンの再有効化で
// 画面が固まる（無限ロード）のを防ぐ。
export function uiShowError(msg) {
    console.error("System Error:", msg);
    alert("通信エラー、またはシステムが応答しませんでした。\n詳細: " + msg);
    const loader = document.getElementById('loading');
    if (loader) loader.classList.add('hidden');
    const btn = document.getElementById('generateBtn');
    if (btn) btn.disabled = false;
}
