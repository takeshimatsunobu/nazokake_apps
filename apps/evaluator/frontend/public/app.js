// @ts-nocheck -- 未移行(段階的にJSDoc型付けを進める対象。window.*グローバル多用のため一括除外)
import { ensureAnonAuth, auth } from "ui/auth";
ensureAnonAuth().catch(err => console.error("認証初期化エラー:", err));

import { APP_URL } from "config";
import { appState } from "state";
import { apiLogEvent, apiGenerate, apiGetStatus, apiSubmitHumanRiddle, apiFetchFeed, apiSubmitFeedEvaluation, apiSubmitFeedback, apiFetchBoard, apiPostBoard } from "api";
import { uiSwitchTab } from "ui/tabs";
import {
    uiGenReset, uiGenLoadingStart, uiGenLoadingStop, uiRenderGenResult, uiShowResult,
    setSubmitModelRatingHandler,
} from "ui/result";
import {
    uiFeedClear, uiFeedShowLoading, uiFeedShowEnd, uiFeedShowEmpty, uiRenderFeed,
    uiFeedShowRetry, uiFeedGetEvaluationInput, uiFeedRemoveCard,
} from "ui/feed";
import { showToast, uiShowError } from "ui/toast";
import { uiShowReplyForm, uiHideReplyForm, uiBoardShowLoading, uiRenderBoard, uiGetBoardInput } from "ui/board";
import { uiFeedbackShowSending, uiFeedbackShowSuccess } from "ui/feedback";

async function logEvent(eventName, tabName = "") {
    let duration = 0; if (eventName === 'page_leave') duration = (Date.now() - appState.sessionStartTime) / 1000;
    await apiLogEvent(eventName, duration, tabName);
}

// HTMLのdata-actionから呼べるようexportする（Controllerの役割）
export function switchTab(tabId) {
    // 1. 純粋なUI操作を呼び出し (View)
    uiSwitchTab(tabId);

    // 2. ビジネスロジックの実行 (Logic)
    logEvent('tab_click', tabId);
    if (tabId === 'board') { loadBoard(); }
    if (tabId === 'feed' && !appState.isUserFeedLoaded) {
        loadUserFeed();
    }
}

export async function shareText(odai, toku, kokoro, score, isHuman) {
    const intro = isHuman ? "私の自作なぞかけ！" : "からくりAIのなぞかけ！";
    const shareText = `${intro}\n\nお題：「${odai}」\n「${odai}」とかけて、\n「${toku}」ととく。\nそのこころは、\n${kokoro}\n\n分析官の評価: ⭐ ${score}/5.0\n\n#謎掛け学術振興会\n`;
    logEvent('share_sns');
    if (navigator.share) { try { await navigator.share({ title: '謎掛け学術振興会', text: shareText, url: APP_URL }); } catch (e) {} } else {
        try { await navigator.clipboard.writeText(shareText + "\n" + APP_URL); showToast("✨ なぞかけをコピーしました！"); setTimeout(() => { window.open(`https://twitter.com/intent/tweet?text=${encodeURIComponent(shareText + "\n" + APP_URL)}`, '_blank'); }, 500); } catch (e) { showToast("コピーに失敗しました", "warning"); }
    }
}

export async function startGeneration() {
    const odai = document.getElementById('odaiInput')?.value.trim(); if (!odai) { showError("お題を入力してください！"); return; }
    // UI制御（前回結果のクリア＋ローディング開始）は ui/result.js に委譲。
    uiGenReset();
    uiGenLoadingStart();
    logEvent('generate_requested');
    try { const data = await apiGenerate(odai); pollStatus(data.task_id); } catch (e) { showError(e.message); }
}
// 段階開示ポーリング。本文が出た時点(gemini_generated)からデュアルカードを描画し、
// 状態が進むたび(gemini_completed → all_completed)に冪等に再描画する。
//  - gemini_generated : Gemini 本文のみ表示・評価欄は「🔍 分析官が採点中...」
//  - gemini_completed : Gemini にスコア付与（ELYZA は生成/採点中）
//  - all_completed    : ELYZA も出揃い完了（'completed' は旧データ互換）
async function pollStatus(taskId) {
    try {
        const data = await apiGetStatus(taskId);
        if (data.status === 'error' || data.eval_status === 'error') { throw new Error(data.message || "エラー"); }
        const shown = ['gemini_generated', 'gemini_completed', 'all_completed', 'completed'].includes(data.status);
        if (shown) {
            uiGenLoadingStop();
            uiRenderGenResult(data, taskId);
        }
        if (data.status === 'all_completed' || data.status === 'completed') { return; } // 全完了。ポーリング終了
        setTimeout(() => pollStatus(taskId), 2000);
    } catch (e) { showError(e.message); }
}

// 鑑定フォームの送信ロジック（ビジネスロジック）。UI制御は ui/form.js が担当し、
// 入力値は引数で受け取る。完了するまで解決される Promise を返す（ローディング解除は form.js 側）。
export async function submitHumanRiddle({ odai, toku, kokoro, nazokakeText }) {
    logEvent('human_submit');
    const data = await apiSubmitHumanRiddle(odai, nazokakeText);
    await pollHumanStatus(data.doc_id, odai, toku, kokoro);
}
// 鑑定結果のステータスをポーリングする。完了で resolve、通信エラーで reject する Promise を返す。
function pollHumanStatus(taskId, odai, toku, kokoro) {
    return new Promise((resolve, reject) => {
        const poll = async () => {
            try {
                const data = await apiGetStatus(taskId);
                if (data.status === 'completed') {
                    uiShowResult({ data, odai, toku, kokoro });
                    resolve();
                } else {
                    setTimeout(poll, 2000);
                }
            } catch (e) {
                reject(e);
            }
        };
        poll();
    });
}

let lastDocId = null;
let isFetchingFeed = false;
let hasMoreFeed = true;
let feedObserver = null;

export function loadUserFeed() {
    lastDocId = null;
    hasMoreFeed = true;
    appState.isUserFeedLoaded = true;
    uiFeedClear();               // View: 一覧クリア（sentinelは兄弟要素なので破壊されない）
    setupIntersectionObserver();   // Logic: observer を再接続（クリア後の順序を厳守）
    fetchNextFeedBatch();
}

function setupIntersectionObserver() {
    if(feedObserver) feedObserver.disconnect();
    const sentinel = document.getElementById('feed-sentinel');
    if (!sentinel) return;
    feedObserver = new IntersectionObserver((entries) => {
        if(entries[0].isIntersecting && !isFetchingFeed && hasMoreFeed) {
            fetchNextFeedBatch();
        }
    }, { rootMargin: "200px" });
    feedObserver.observe(sentinel);
}

export async function fetchNextFeedBatch() {
    if (isFetchingFeed || !hasMoreFeed) return;   // Logic: 多重フェッチ防止（ガードはController維持）
    isFetchingFeed = true;
    uiFeedShowLoading();                            // View: sentinelにローディング
    try {
        const data = await apiFetchFeed(lastDocId, 5);
        if (!data.items || data.items.length === 0) {
            hasMoreFeed = false;
            uiFeedShowEnd();                        // View: 終端メッセージ
            if (!lastDocId) uiFeedShowEmpty();       // View: 初回かつ0件なら空状態
        } else {
            uiRenderFeed(data.items);
            lastDocId = data.items[data.items.length - 1].doc_id;
        }
    } catch (e) {
        showToast("読み込みエラー", "warning");
        uiFeedShowRetry(fetchNextFeedBatch);        // View: 再試行ボタン（コールバック注入）
    } finally {
        isFetchingFeed = false;
    }
}

export async function submitUserEvaluation(docId) {
    const input = uiFeedGetEvaluationInput(docId);   // View: 入力値の読取
    if (input.score === 0) { showToast("⚠️ 星を選択してください", "warning"); return; }
    logEvent('evaluate_feed');
    try {
        await apiSubmitFeedEvaluation(docId, { odai: input.odai, toku: input.toku, kokoro: input.kokoro, s_total: input.score, human_comment: input.comment });
        // Logic: 状態確定（リロード後も評価済みを保持）はアニメ前に行う
        appState.evaluatedItems.push(docId); localStorage.setItem('nazokake_evaluated', JSON.stringify(appState.evaluatedItems));
        showToast("✨ 評価・添削ありがとうございます！");
        uiFeedRemoveCard(docId);                     // View: カード退場アニメ
    } catch (e) { showToast("エラー", 'warning'); }
}

export async function submitFeedback() {
    const score = parseInt(document.getElementById('feedback-score').value);
    const comment = document.getElementById('feedback-comment').value.trim();
    if (score === 0 && comment === "") { showToast("⚠️ 評価かコメントのどちらかを入力してください", "warning"); return; }
    uiFeedbackShowSending();
    try {
        await apiSubmitFeedback(score, comment);
        logEvent('submit_feedback');
        uiFeedbackShowSuccess();
    } catch (e) { showToast("送信に失敗しました。時間をおいてお試しください。", "warning"); setTimeout(() => location.reload(), 2000); }
}
window.addEventListener('load', () => { logEvent('page_view'); });
window.addEventListener('beforeunload', () => { logEvent('page_leave'); });

// showError 本体は ui/toast.js の uiShowError へ移設。ここは後方互換のためのエイリアス。
export function showError(msg) {
    uiShowError(msg);
}

// Gemini / ELYZA 各モデルへの評価を「別々に」DB(telemetry_logs)へ記録する（ui/result.js から呼ばれる）。
// event_name でモデルを区別し、score を duration、task(doc) id を tab_name、コメントを comment に載せる。
export async function submitModelRating(model, docId, score, comment = '') {
    await apiLogEvent('gen_eval:' + model, Number(score) || 0, docId || '', comment || '');
}
// ui/result.js から submitModelRating を呼べるよう結線する（result.js -> app.js の直接importは
// 循環importになるため、コールバック注入で結ぶ。ui/form.jsのuiInitForm(onSubmit)と同じ設計）。
setSubmitModelRatingHandler(submitModelRating);

// =========================================================================
// 🚀 [グロースハック・パッチ] ウォーターマーク画像化 ＆ 動的ディープリンク
// =========================================================================

// 1. 動的ディープリンクの待ち受け (?nazo_id=xxx)
document.addEventListener('DOMContentLoaded', async () => {
    const urlParams = new URLSearchParams(window.location.search);
    const nazoId = urlParams.get('id') || urlParams.get('nazo_id');
    if (nazoId) {
        try {
            showToast("共有されたなぞかけを読み込んでいます...", "info");

            // APIから単体データを取得
            const data = await apiGetStatus(nazoId);

            if (data && data.odai) {
                data.doc_id = nazoId; // フィードUI互換用ID
                switchTab('feed');
                uiFeedClear();
                // 共有されたデータをフィードの最上段に強制レンダリング
                uiRenderFeed([data]);
                showToast("✨ 共有された作品を表示しました！");
                setTimeout(() => {
                    const targetCard = document.getElementById('feed-container')?.firstElementChild;
                    if (targetCard) targetCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }, 300);
            }
        } catch(e) {
            console.error("DeepLink Error:", e);
            showToast("指定された作品が見つかりませんでした", "warning");
        }
    }
});

// 2. シェア機能の完全オーバーライド (html2canvasによる画像化＆落款合成)
export async function shareTextResult(type) {
    if (!window.html2canvas) {
        alert("画像生成ライブラリの読み込みを待っています。もう一度お試しください。");
        return;
    }

    const targetElement = document.getElementById('result-content');
    const ogA = document.getElementById('og-a').textContent;
    const ogB = document.getElementById('og-b').textContent;
    const ogC = document.getElementById('og-c').textContent;

    // ✨ 落款ウォーターマークの生成
    const watermark = document.createElement('div');
    watermark.className = 'absolute bottom-2 right-2 flex flex-col items-end opacity-90 z-50 pointer-events-none transform rotate-[-2deg]';
    watermark.innerHTML = `
        <div class="bg-red-700 text-white text-[10px] font-black tracking-widest px-2 py-0.5 rounded shadow-sm border border-red-800">
            謎掛道場
        </div>
        <div class="text-[8px] text-gray-500 font-bold bg-white/80 px-1 rounded-sm mt-0.5">
            nazokake.com
        </div>
    `;

    // 💥 ここで抜けていた originalClass と originalBackdrop の定義と、try の開始を復活！
    const originalClass = targetElement.className;
    const originalBackdrop = targetElement.style.backdropFilter;
    try {
        // 画像生成用の一時的なスタイル変更
        targetElement.className = "bg-[#FAF8F5] p-6 sm:p-8 rounded-2xl relative mt-4 shadow-xl border-2 border-[#C5B358] max-w-lg mx-auto overflow-hidden";
        targetElement.style.backdropFilter = "none";
        targetElement.style.margin = "0";

        // ウォーターマークを追加
        targetElement.appendChild(watermark);

        const canvas = await html2canvas(targetElement, {
            backgroundColor: "#FAF8F5",
            scale: 2,
            useCORS: true,
            logging: false,
            onclone: (clonedDoc) => {
                const clonedTarget = clonedDoc.getElementById('result-content');
                if(clonedTarget) {
                    clonedTarget.style.boxShadow = "none";
                }
            }
        });

        // ウォーターマークとスタイルを元に戻す
        watermark.remove();
        targetElement.className = originalClass;
        targetElement.style.backdropFilter = originalBackdrop;
        targetElement.style.margin = "";

        // SNSシェア処理
        canvas.toBlob(async (blob) => {
            if (!blob) {
                alert("画像の生成に失敗しました。");
                return;
            }

            const cleanA = ogA.replace(/「|」|とかけて/g, '').trim();
            const text = `「${cleanA}」のなぞかけで高評価を獲得しました！

#なぞかけ #AIなぞかけ道場`;

            if (type === 'x') {
                const intentUrl = `https://twitter.com/intent/tweet?text=${encodeURIComponent(text)}&url=${encodeURIComponent('https://nazokake-dojo.web.app/')}`;
                window.open(intentUrl, '_blank');
            } else if (type === 'share' && navigator.share) {
                const file = new File([blob], 'nazokake_result.png', { type: 'image/png' });
                try {
                    await navigator.share({
                        title: 'なぞかけ道場',
                        text: text,
                        files: [file]
                    });
                } catch (err) {
                    if (err.name !== 'AbortError') {
                        console.error('Share failed:', err);
                    }
                }
            } else {
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = 'nazokake_result.png';
                a.click();
                URL.revokeObjectURL(url);
            }
        }, 'image/png');

    } catch (e) {
        console.error("画像生成エラー:", e);
        alert("画像の生成中にエラーが発生しました。");
        // エラー時も確実に元に戻す
        if(watermark.parentNode) watermark.remove();
        targetElement.className = originalClass;
        targetElement.style.backdropFilter = originalBackdrop;
        targetElement.style.margin = "";
    }


}

// === 掲示板ロジック (Controller) ===

// 状態管理: 現在のカテゴリ（初期値はなぞかけ）
let currentBoardCategory = 'nazokake';

export function switchBoardCategory(category) {
    currentBoardCategory = category;

    const tabNazo = document.getElementById('board-tab-nazokake');
    const tabAi = document.getElementById('board-tab-ai');

    if (tabNazo && tabAi) {
        if (category === 'nazokake') {
            tabNazo.className = 'px-5 py-2 rounded-full font-bold text-sm bg-[#2C3539] text-[#C5B358] shadow-md border border-[#C5B358] transition-all';
            tabAi.className = 'px-5 py-2 rounded-full font-bold text-sm bg-white/70 text-gray-600 hover:bg-white border border-gray-300 shadow-sm transition-all';
        } else {
            tabAi.className = 'px-5 py-2 rounded-full font-bold text-sm bg-[#2C3539] text-[#C5B358] shadow-md border border-[#C5B358] transition-all';
            tabNazo.className = 'px-5 py-2 rounded-full font-bold text-sm bg-white/70 text-gray-600 hover:bg-white border border-gray-300 shadow-sm transition-all';
        }
    }

    // B案: タブ切り替え時に自動的にFetchを発火させる
    loadBoard();
}

export async function loadBoard() {
    uiBoardShowLoading();
    try {
        const data = await apiFetchBoard(currentBoardCategory);
        uiRenderBoard(data.items);
    } catch (e) {
        showToast("掲示板の読み込みに失敗しました", "warning");
    }
}

export async function submitBoardPost(parentId = null) {
    const body = uiGetBoardInput(parentId);
    if (!body) {
        showToast("本文を入力してください", "warning");
        return;
    }

    try {
        let idToken;
        if (auth && auth.currentUser) {
            idToken = await auth.currentUser.getIdToken(true);
        } else {
            idToken = await ensureAnonAuth();
        }

        await apiPostBoard(body, parentId, idToken, currentBoardCategory);

        uiHideReplyForm();
        const mainInput = document.getElementById('board-main-input');
        if (mainInput) mainInput.value = '';

        loadBoard();
        showToast("書き込みました！", "success");
    } catch (e) {
        showToast(e.message || "書き込みに失敗しました", "warning");
    }
}


// ============================================================================
// 研究データ動的ロード機能 (JSONファースト・アーキテクチャ)
// ============================================================================
export async function loadResearchData() {
    const container = document.getElementById('research-data-container');
    if (!container) return; // 該当タブが開かれていない・コンテナがない場合は何もしない

    try {
        const response = await fetch('/research_data.json');
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        const data = await response.json();

        let htmlBuffer = '';

        data.chapters.forEach(chapter => {
            let itemsHtml = chapter.items.map(item => `
                <div class="bg-white rounded-xl p-4 border border-[#C5B358]/20 shadow-xs">
                    <div class="flex items-start gap-2 mb-1">
                        <span class="text-sm shrink-0">${uiEscapeHtmlSafe(item.icon)}</span>
                        <h5 class="font-bold text-sm text-gray-800 leading-snug">${uiEscapeHtmlSafe(item.id)} ${uiEscapeHtmlSafe(item.title)}</h5>
                    </div>
                    <p class="text-[11px] text-gray-500 italic mb-2">“${uiEscapeHtmlSafe(item.description)}”</p>
                    <div class="inline-block bg-[#FAF8F5] text-[#5B8124] text-[9px] font-bold px-2 py-0.5 rounded border border-[#5B8124]/20">${uiEscapeHtmlSafe(item.category)}</div>
                </div>
            `).join('');

            htmlBuffer += `
                <div class="border-l-4 border-[#902A19] pl-3 py-0.5 sticky top-0 bg-[#FAF8F5] z-10 pt-4">
                    <h4 class="font-bold text-[#902A19] text-sm md:text-base">${uiEscapeHtmlSafe(chapter.title)}</h4>
                </div>
                <div class="grid grid-cols-1 md:grid-cols-2 gap-3 mt-3 mb-6">
                    ${itemsHtml}
                </div>
            `;
        });

        // 最後に一括でDOMへマウント（リフロー抑制）
        container.innerHTML = htmlBuffer;

    } catch (error) {
        console.error('研究データの読み込みに失敗しました:', error);
        container.innerHTML = `
            <div class="text-center py-10 text-[#902A19] font-bold border border-[#902A19]/30 rounded-xl bg-[#FAF8F5]">
                データの読み込みに失敗しました。<br>通信環境をご確認の上、再読み込みしてください。
            </div>`;
    }
}

// loadResearchData専用のXSSエスケープ(uiEscapeHtmlと同一実装。ui/result.jsをこの用途だけで
// importする必要は無いため、ここに自己完結させる)。
function uiEscapeHtmlSafe(str) {
    return String(str ?? '').replace(/[&<>'"]/g,
        tag => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'}[tag] || tag)
    );
}

// 初期ロード時の発火
document.addEventListener('DOMContentLoaded', loadResearchData);
