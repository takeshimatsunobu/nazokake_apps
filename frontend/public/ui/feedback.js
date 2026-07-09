// frontend/public/ui/feedback.js
// 「ご意見箱」フォームのUI制御（View）。
// 星評価の見た目切替と、送信中／完了の表示生成を担う。
// 実際のAPI送信（ビジネスロジック）は app.js（Controller）の submitFeedback が行う。

// 満足度（星）の選択状態を反映する
window.setFeedbackRating = function(score) {
    document.getElementById('feedback-score').value = score;
    for (let i = 1; i <= 5; i++) {
        const btn = document.getElementById(`fb-star-${i}`);
        if (i <= score) {
            btn.classList.add('bg-[#C5B358]', 'text-white', 'scale-110', 'border-[#C5B358]', 'shadow-md');
            btn.classList.remove('bg-white', 'text-gray-300', 'scale-100', 'border-gray-200', 'shadow-sm');
        } else {
            btn.classList.remove('bg-[#C5B358]', 'text-white', 'scale-110', 'border-[#C5B358]', 'shadow-md');
            btn.classList.add('bg-white', 'text-gray-300', 'scale-100', 'border-gray-200', 'shadow-sm');
        }
    }
};

// 送信中の表示（通信鳩スピナー）
window.uiFeedbackShowSending = function() {
    document.getElementById('feedback-form-container').innerHTML = `<div class="text-center py-8 bg-[#FAF8F5] rounded-lg border border-[#C5B358]/50 shadow-inner"><div class="animate-spin rounded-full h-8 w-8 border-b-2 border-[#C5B358] mx-auto mb-4"></div><p class="text-gray-600 font-bold text-sm">通信鳩が手紙を運んでいます...</p></div>`;
};

// 送信完了の表示
window.uiFeedbackShowSuccess = function() {
    document.getElementById('feedback-form-container').innerHTML = `<div class="text-center py-8 bg-green-50 rounded-lg border border-green-200 shadow-inner"><p class="text-3xl mb-2">✨</p><p class="text-green-700 font-bold">貴重なご意見、確かに承りました！</p><p class="text-gray-500 text-xs mt-2">今後のアプリ改善に役立たせていただきます。</p></div>`;
};
