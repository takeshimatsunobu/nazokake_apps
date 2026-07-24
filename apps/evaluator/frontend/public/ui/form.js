// @ts-nocheck -- 未移行(段階的にJSDoc型付けを進める対象)
// frontend/public/ui/form.js
// 自作なぞかけ鑑定フォームのUI制御（View）。
// 送信イベントの監視・入力値の取得・バリデーション・ローディング/ボタンの切り替えを担う。
// 実際のAPI通信（ビジネスロジック）は uiInitForm に渡される onSubmit コールバックへ委譲する。

import { showToast } from "ui/toast";

// ローディング表示と送信ボタンの活性/非活性をまとめて切り替える
export function uiFormSetLoading(isLoading) {
    const btn = document.getElementById('humanSubmitBtn');
    const loading = document.getElementById('human-loading');
    if (isLoading) {
        if (btn) btn.disabled = true;
        document.getElementById('human-result-card')?.classList.add('hidden');
        loading?.classList.remove('hidden');
    } else {
        if (btn) btn.disabled = false;
        loading?.classList.add('hidden');
    }
}

// 鑑定フォームを初期化する。
// onSubmit には { odai, toku, kokoro, nazokakeText } を受け取り、
// 鑑定完了まで解決される Promise を返す非同期処理（API通信）を渡す。
export function uiInitForm(onSubmit) {
    const btn = document.getElementById('humanSubmitBtn');
    if (!btn) return;

    btn.addEventListener('click', async () => {
        // 入力値の取得
        const odai = document.getElementById('hOdai')?.value.trim();
        const toku = document.getElementById('hToku')?.value.trim();
        const kokoro = document.getElementById('hKokoro')?.value.trim();

        // バリデーション
        if (!odai || !toku || !kokoro) {
            showToast("⚠️ すべて入力してください", "warning");
            return;
        }
        const nazokakeText = `「${odai}」とかけて、「${toku}」と解く。\nその心は、${kokoro}`;

        // ローディング開始 → API通信（注入されたロジック）→ 完了/失敗で必ず解除
        uiFormSetLoading(true);
        try {
            await onSubmit({ odai, toku, kokoro, nazokakeText });
        } catch (e) {
            showToast(e.message || "エラー", "warning");
        } finally {
            uiFormSetLoading(false);
        }
    });
}
