// frontend/app.js
// Phase1(生成UIの骨格・段階的ローディング) + Phase2(タイムライン描画・座布団・
// 自分の生成物のリアルタイム合流)のコントローラ。
//
// 【段階的ローディングについての注記】バックエンド(POST /v1/generate)はStep1/Step2の
// 進捗を返さない完全同期の単発APIであり、SSE/WebSocket/ジョブポーリングは実装されて
// いない(ファクトチェック結果)。そのため以下のLOADING_STAGESはサーバーの実イベント
// ではなく、経過時間に応じてメッセージを切り替える演出であることを明記しておく。
import {
    appState, markAsMine, isMine, hasReactedZabuton, markZabutonReacted,
    getCachedBlockedUntil, setCachedBlockedUntil, getPenName, setPenName,
} from "state";
import {
    apiFetchPersonas, apiGenerate, apiFetchTimeline, apiZabuton,
    apiSubmitUnlockRequest, apiSubmitCorrection,
} from "api";

const TIMELINE_PAGE_SIZE = 20;
const NEW_ITEMS_POLL_MS = 25000;

const LOADING_STAGES = [
    "🔍 お題を解析中...",
    "🎭 ペルソナに憑依中...",
    "🧠 掛詞をひねり出し中...",
    "✨ 仕上げ中...",
];

// タイムラインへ既に描画済みのdoc_id(初期ロード・もっと読み込む・新着ポーリング・
// 自分の生成の四箇所から重複して差し込まれるのを防ぐ)。
const renderedDocIds = new Set();
let nextBeforeCursor = null;
let pendingNewItems = [];

// ------------------------------------------------------------
// 小さなユーティリティ
// ------------------------------------------------------------

// LLM/Firestore由来のテキストをinnerHTMLへ差し込む前に必ず通す(XSS対策)。
function escapeHtml(s) {
    return String(s == null ? "" : s)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

function showToast(message, kind = "info") {
    const container = document.getElementById("toast-container");
    if (!container) return;
    const bg = kind === "warning" ? "bg-amber-600" : kind === "error" ? "bg-rose-600" : "bg-slate-800";
    const el = document.createElement("div");
    el.className = `${bg} text-white text-sm font-bold px-4 py-2 rounded-full shadow-lg opacity-0 -translate-y-2 transition-all duration-300`;
    el.textContent = message;
    container.appendChild(el);
    requestAnimationFrame(() => el.classList.remove("opacity-0", "-translate-y-2"));
    setTimeout(() => {
        el.classList.add("opacity-0");
        setTimeout(() => el.remove(), 300);
    }, 2600);
}

function personaName(personaId) {
    const found = appState.personas.find((p) => p.persona_id === personaId);
    return found ? found.name : `ペルソナ#${personaId}`;
}

// ------------------------------------------------------------
// ペルソナ選択チップ(下段・生成UI)
// ------------------------------------------------------------

function renderPersonaChips() {
    const wrap = document.getElementById("persona-chips");
    if (!wrap) return;
    wrap.innerHTML = appState.personas
        .map((p) => {
            const active = p.persona_id === appState.selectedPersonaId;
            const cls = active
                ? "bg-indigo-600 text-white border-indigo-600"
                : "bg-white text-slate-700 border-slate-300";
            return `<button type="button" data-persona-id="${p.persona_id}"
                class="persona-chip shrink-0 whitespace-nowrap text-xs font-bold px-3 py-1.5 rounded-full border ${cls}">
                ${escapeHtml(p.name)}
            </button>`;
        })
        .join("");
}

function onPersonaChipsClick(ev) {
    const btn = ev.target.closest("[data-persona-id]");
    if (!btn) return;
    appState.selectedPersonaId = Number(btn.dataset.personaId);
    renderPersonaChips();
}

// ------------------------------------------------------------
// タイムライン(上段)
// ------------------------------------------------------------

function cardHtml(item) {
    const mine = isMine(item.doc_id);
    const reacted = hasReactedZabuton(item.doc_id);
    const isRouteB = item.is_valid_for_training === false;

    // ルートB(異常入力のエンタメ回答)は非表示にせず、「ネタ回答」バッジ付きの
    // 見た目で区別する(要件で明示された、UI側の表示可否・見せ方の制御)。
    const routeBadge = isRouteB
        ? `<span class="inline-block text-[10px] font-bold px-2 py-0.5 rounded-full bg-fuchsia-100 text-fuchsia-700 border border-fuchsia-300">🤹 ネタ回答</span>`
        : "";
    const mineBadge = mine
        ? `<span class="inline-block text-[10px] font-bold px-2 py-0.5 rounded-full bg-indigo-100 text-indigo-700 border border-indigo-300">YOU</span>`
        : "";
    const cardBorder = isRouteB ? "border-dashed border-fuchsia-300" : "border-slate-200";

    return `
    <article data-doc-id="${escapeHtml(item.doc_id)}"
        class="timeline-card rounded-2xl border ${cardBorder} bg-white p-4 shadow-sm">
        <div class="flex items-center justify-between gap-2 mb-1.5">
            <span class="text-[11px] font-bold text-slate-500">${escapeHtml(personaName(item.persona_id))}</span>
            <div class="flex items-center gap-1">${mineBadge}${routeBadge}</div>
        </div>
        <p class="text-xs text-slate-400 mb-1">お題「${escapeHtml(item.odai)}」</p>
        <p class="nazokake-body text-[15px] leading-relaxed text-slate-800 whitespace-pre-wrap mb-3">${escapeHtml(item.nazokake_text)}</p>
        <div class="flex items-center gap-3">
            <button type="button" data-action="zabuton" data-doc-id="${escapeHtml(item.doc_id)}"
                ${reacted ? "disabled" : ""}
                class="zabuton-btn text-xs font-bold px-3 py-1.5 rounded-full border ${reacted ? "bg-slate-100 text-slate-400 border-slate-200" : "bg-amber-50 text-amber-700 border-amber-300 active:scale-95"}">
                🪑 座布団 <span class="zabuton-count">${item.zabuton_count}</span>
            </button>
            <button type="button" data-action="redpen" data-doc-id="${escapeHtml(item.doc_id)}"
                class="text-xs font-bold px-3 py-1.5 rounded-full border bg-rose-50 text-rose-700 border-rose-300 active:scale-95">
                🖊️ 赤ペン
            </button>
        </div>
    </article>`;
}

function renderInitialTimeline(items) {
    const list = document.getElementById("timeline-list");
    if (!list) return;
    list.innerHTML = items.map(cardHtml).join("") || emptyStateHtml();
    items.forEach((it) => renderedDocIds.add(it.doc_id));
    if (items.length) {
        appState.newestSeenCreatedAt = items[0].created_at;
    }
}

function emptyStateHtml() {
    // "timeline-empty-state"クラスはprependToTimeline()が最初の1件挿入時に
    // この要素を検出・除去するために使う(この名前を変える場合は両方合わせて変更)。
    return `<p class="timeline-empty-state text-center text-sm text-slate-400 py-10">まだなぞかけがありません。下段から最初の1件を作ってみましょう。</p>`;
}

function appendMoreToTimeline(items) {
    const list = document.getElementById("timeline-list");
    if (!list) return;
    const fresh = items.filter((it) => !renderedDocIds.has(it.doc_id));
    fresh.forEach((it) => renderedDocIds.add(it.doc_id));
    list.insertAdjacentHTML("beforeend", fresh.map(cardHtml).join(""));
}

function prependToTimeline(item) {
    if (renderedDocIds.has(item.doc_id)) return;
    renderedDocIds.add(item.doc_id);
    const list = document.getElementById("timeline-list");
    if (!list) return;
    const empty = list.querySelector(".timeline-empty-state");
    if (empty) empty.remove();
    list.insertAdjacentHTML("afterbegin", cardHtml(item));
    const card = list.firstElementChild;
    if (card) {
        card.classList.add("ring-2", "ring-indigo-400");
        setTimeout(() => card.classList.remove("ring-2", "ring-indigo-400"), 1500);
    }
    if (!appState.newestSeenCreatedAt || item.created_at > appState.newestSeenCreatedAt) {
        appState.newestSeenCreatedAt = item.created_at;
    }
}

async function loadInitialTimeline() {
    try {
        const data = await apiFetchTimeline({ limit: TIMELINE_PAGE_SIZE });
        renderInitialTimeline(data.items);
        nextBeforeCursor = data.next_before;
        updateLoadMoreVisibility();
    } catch (e) {
        showToast(`タイムラインの取得に失敗しました: ${e.message}`, "error");
    }
}

async function loadMoreTimeline() {
    if (!nextBeforeCursor) return;
    const btn = document.getElementById("load-more-btn");
    if (btn) btn.disabled = true;
    try {
        const data = await apiFetchTimeline({ before: nextBeforeCursor, limit: TIMELINE_PAGE_SIZE });
        appendMoreToTimeline(data.items);
        nextBeforeCursor = data.next_before;
    } catch (e) {
        showToast(`追加読み込みに失敗しました: ${e.message}`, "error");
    } finally {
        if (btn) btn.disabled = false;
        updateLoadMoreVisibility();
    }
}

function updateLoadMoreVisibility() {
    const btn = document.getElementById("load-more-btn");
    if (!btn) return;
    btn.classList.toggle("hidden", !nextBeforeCursor);
}

// ------------------------------------------------------------
// 新着ポーリング(他ユーザーの投稿を「🆕 新着」ピルで知らせる、非破壊的に反映)
// ------------------------------------------------------------

async function pollForNewItems() {
    try {
        const data = await apiFetchTimeline({ limit: 5 });
        const unseen = data.items.filter((it) => !renderedDocIds.has(it.doc_id));
        if (!unseen.length) return;
        // 既にpendingにあるものと重複させない。
        const pendingIds = new Set(pendingNewItems.map((it) => it.doc_id));
        unseen.forEach((it) => {
            if (!pendingIds.has(it.doc_id)) pendingNewItems.push(it);
        });
        updateNewItemsPill();
    } catch (e) {
        // ポーリング失敗は静かに無視する(ユーザー操作を止めるほどの重要度ではない)。
        console.warn("新着ポーリング失敗:", e);
    }
}

function updateNewItemsPill() {
    const pill = document.getElementById("new-items-pill");
    if (!pill) return;
    if (pendingNewItems.length === 0) {
        pill.classList.add("hidden");
        return;
    }
    pill.textContent = `🆕 新着 ${pendingNewItems.length}件`;
    pill.classList.remove("hidden");
}

function flushPendingNewItems() {
    // created_at昇順(古い→新しい)で1件ずつprependすると、最終的に新しい順で並ぶ。
    const sorted = [...pendingNewItems].sort((a, b) => (a.created_at < b.created_at ? -1 : 1));
    sorted.forEach((it) => prependToTimeline(it));
    pendingNewItems = [];
    updateNewItemsPill();
    document.getElementById("timeline-area")?.scrollTo({ top: 0, behavior: "smooth" });
}

// ------------------------------------------------------------
// タイムライン上のアクション(座布団・赤ペン、イベント委譲)
// ------------------------------------------------------------

async function onTimelineClick(ev) {
    const zabutonBtn = ev.target.closest('[data-action="zabuton"]');
    if (zabutonBtn) {
        await handleZabuton(zabutonBtn);
        return;
    }
    const redpenBtn = ev.target.closest('[data-action="redpen"]');
    if (redpenBtn) {
        const card = redpenBtn.closest(".timeline-card");
        const original = card?.querySelector(".nazokake-body")?.textContent || "";
        openRedpenModal(redpenBtn.dataset.docId, original);
    }
}

async function handleZabuton(btn) {
    const docId = btn.dataset.docId;
    if (hasReactedZabuton(docId)) return;
    btn.disabled = true;
    // 通信を待たずに見た目だけ先に更新する(操作の手応えを優先。失敗時は元に戻す)。
    const countEl = btn.querySelector(".zabuton-count");
    const prevCount = countEl ? Number(countEl.textContent) : 0;
    if (countEl) countEl.textContent = String(prevCount + 1);
    btn.classList.add("bg-slate-100", "text-slate-400", "border-slate-200");
    btn.classList.remove("bg-amber-50", "text-amber-700", "border-amber-300");

    try {
        const res = await apiZabuton(docId);
        if (countEl) countEl.textContent = String(res.zabuton_count);
        markZabutonReacted(docId);
    } catch (e) {
        // 失敗時は見た目を戻す(座布団を送れなかったことをユーザーへ伝える)。
        if (countEl) countEl.textContent = String(prevCount);
        btn.disabled = false;
        btn.classList.remove("bg-slate-100", "text-slate-400", "border-slate-200");
        btn.classList.add("bg-amber-50", "text-amber-700", "border-amber-300");
        showToast(`座布団を送れませんでした: ${e.message}`, "error");
    }
}

// ------------------------------------------------------------
// 下段・生成UI(Phase1: 段階的ローディング付き同期生成)
// ------------------------------------------------------------

function startLoadingAnimation() {
    const stageEl = document.getElementById("loading-stage");
    const loadingWrap = document.getElementById("loading-wrap");
    if (!stageEl || !loadingWrap) return () => {};

    loadingWrap.classList.remove("hidden");
    let i = 0;
    stageEl.textContent = LOADING_STAGES[0];
    const timer = setInterval(() => {
        i = (i + 1) % LOADING_STAGES.length;
        stageEl.textContent = LOADING_STAGES[i];
    }, 1200);

    return () => {
        clearInterval(timer);
        loadingWrap.classList.add("hidden");
    };
}

async function onGenerateSubmit(ev) {
    ev.preventDefault();
    const input = document.getElementById("odai-input");
    const btn = document.getElementById("generate-btn");
    const odai = (input?.value || "").trim();
    if (!odai) {
        showToast("お題を入力してください", "warning");
        return;
    }

    btn.disabled = true;
    const stopLoading = startLoadingAnimation();

    try {
        const result = await apiGenerate(odai, appState.selectedPersonaId, appState.uid);

        if (result.route === "BLOCKED") {
            showBlockScreen(result);
            return;
        }

        markAsMine(result.doc_id);
        // 要件: 自分の生成物は「即座に」公開タイムラインへ合流させる。
        // 生成APIのレスポンスをそのままタイムライン先頭へoptimistic prependすれば
        // 足りるため、Firestoreリアルタイムリスナー等の追加インフラは不要
        // (ファクトチェックの結論)。
        prependToTimeline({
            doc_id: result.doc_id,
            odai: result.odai,
            persona_id: result.persona_id,
            route: result.route,
            toku: result.toku,
            kokoro: result.kokoro,
            nazokake_text: result.nazokake_text,
            is_valid_for_training: result.is_valid_for_training,
            zabuton_count: 0,
            created_at: new Date().toISOString(),
        });
        document.getElementById("timeline-area")?.scrollTo({ top: 0, behavior: "smooth" });

        if (result.is_valid_for_training) {
            showToast("✨ なぞかけが完成しました!", "info");
        } else {
            showToast("🤹 変化球のお題でしたが、見事に切り返しました!", "warning");
        }
        input.value = "";
    } catch (e) {
        showToast(`生成に失敗しました: ${e.message}`, "error");
    } finally {
        stopLoading();
        btn.disabled = false;
    }
}

// ------------------------------------------------------------
// 段階的ブロック: 「ユーモアの充電期間」オーバーレイ
// ------------------------------------------------------------

let blockCountdownTimer = null;

function formatRemaining(blockedUntilIso) {
    const diffMs = new Date(blockedUntilIso).getTime() - Date.now();
    if (diffMs <= 0) return null;
    const totalMinutes = Math.ceil(diffMs / 60000);
    const days = Math.floor(totalMinutes / (60 * 24));
    const hours = Math.floor((totalMinutes % (60 * 24)) / 60);
    const minutes = totalMinutes % 60;
    if (days > 0) return `復帰まで あと${days}日${hours}時間`;
    if (hours > 0) return `復帰まで あと${hours}時間${minutes}分`;
    return `復帰まで あと${minutes}分`;
}

function updateBlockCountdown(blockedUntilIso) {
    const remainingEl = document.getElementById("block-remaining");
    const remaining = formatRemaining(blockedUntilIso);
    if (!remaining) {
        // 充電完了。オーバーレイを閉じてキャッシュも消し、通常操作へ戻す。
        hideBlockScreen();
        showToast("🔋 充電完了!また存分に作ってください", "info");
        return;
    }
    if (remainingEl) remainingEl.textContent = remaining;
}

function showBlockScreen(data) {
    setCachedBlockedUntil(data.blocked_until);

    const overlay = document.getElementById("block-overlay");
    if (!overlay) return;
    document.getElementById("block-odai").textContent = data.odai ? `お題「${data.odai}」` : "";
    document.getElementById("block-nazokake-text").textContent = data.nazokake_text || "";
    document.getElementById("block-unlock-form")?.classList.add("hidden");
    document.getElementById("block-unlock-sent")?.classList.add("hidden");
    document.getElementById("block-unlock-toggle")?.classList.remove("hidden");
    const messageEl = document.getElementById("block-unlock-message");
    if (messageEl) messageEl.value = "";

    overlay.classList.remove("hidden");

    if (blockCountdownTimer) clearInterval(blockCountdownTimer);
    updateBlockCountdown(data.blocked_until);
    blockCountdownTimer = setInterval(() => updateBlockCountdown(data.blocked_until), 30000);
}

function hideBlockScreen() {
    document.getElementById("block-overlay")?.classList.add("hidden");
    if (blockCountdownTimer) {
        clearInterval(blockCountdownTimer);
        blockCountdownTimer = null;
    }
    setCachedBlockedUntil(null);
}

async function handleUnlockSubmit() {
    const messageEl = document.getElementById("block-unlock-message");
    const message = (messageEl?.value || "").trim();
    if (!message) {
        showToast("直談判の内容を入力してください", "warning");
        return;
    }
    const submitBtn = document.getElementById("block-unlock-submit");
    if (submitBtn) submitBtn.disabled = true;
    try {
        await apiSubmitUnlockRequest(appState.uid, message);
        document.getElementById("block-unlock-toggle")?.classList.add("hidden");
        document.getElementById("block-unlock-form")?.classList.add("hidden");
        document.getElementById("block-unlock-sent")?.classList.remove("hidden");
    } catch (e) {
        showToast(`直談判の送信に失敗しました: ${e.message}`, "error");
        if (submitBtn) submitBtn.disabled = false;
    }
}

function initBlockScreen() {
    document.getElementById("block-unlock-toggle")?.addEventListener("click", () => {
        document.getElementById("block-unlock-form")?.classList.remove("hidden");
        document.getElementById("block-unlock-toggle")?.classList.add("hidden");
    });
    document.getElementById("block-unlock-submit")?.addEventListener("click", handleUnlockSubmit);

    // 前回訪問時にブロック中だった場合、リロード一発で復元する
    // (専用のステータス確認APIは持たないため、キャッシュのみを根拠とする)。
    const cached = getCachedBlockedUntil();
    if (cached && formatRemaining(cached)) {
        showBlockScreen({ odai: "", nazokake_text: "只今充電中のため、前回の内容は表示できません。", blocked_until: cached });
    } else if (cached) {
        setCachedBlockedUntil(null);
    }
}

// ------------------------------------------------------------
// Phase3: 「赤ペン」添削モーダル(ペンネーム登録 → 添削 → ハッカーライクなログ演出)
// ------------------------------------------------------------

let redpenTargetDocId = null;

const HACKER_LOG_LINES = [
    "> connecting to nazokake-core.internal ...",
    "> authenticating pen name ...",
    "> parsing kakekotoba structure ...",
    "> diffing original vs corrected ...",
    "> committing DPO candidate pair ...",
    "> done. thank you for your contribution.",
];

function openRedpenModal(docId, originalText) {
    redpenTargetDocId = docId;
    document.getElementById("redpen-original").textContent = originalText || "";
    document.getElementById("redpen-toku").value = "";
    document.getElementById("redpen-kokoro").value = "";
    document.getElementById("redpen-hacker-log").classList.add("hidden");
    document.getElementById("redpen-hacker-log").innerHTML = "";

    const hasPenName = !!getPenName();
    document.getElementById("redpen-penname-step").classList.toggle("hidden", hasPenName);
    document.getElementById("redpen-form-step").classList.toggle("hidden", !hasPenName);

    document.getElementById("redpen-modal")?.classList.remove("hidden");
}

function closeRedpenModal() {
    document.getElementById("redpen-modal")?.classList.add("hidden");
    redpenTargetDocId = null;
}

async function playHackerLogThenClose() {
    const logEl = document.getElementById("redpen-form-step");
    logEl.classList.add("hidden");
    const hackerEl = document.getElementById("redpen-hacker-log");
    hackerEl.classList.remove("hidden");
    hackerEl.innerHTML = "";

    for (const line of HACKER_LOG_LINES) {
        const p = document.createElement("p");
        p.textContent = line;
        hackerEl.appendChild(p);
        hackerEl.scrollTop = hackerEl.scrollHeight;
        await new Promise((resolve) => setTimeout(resolve, 260));
    }
    await new Promise((resolve) => setTimeout(resolve, 700));
    closeRedpenModal();
    showToast("🖊️ 赤ペン添削が届けられました。ありがとうございます!", "info");
}

function handleRedPenPenNameSubmit() {
    const input = document.getElementById("redpen-penname-input");
    const name = (input?.value || "").trim();
    if (!name) {
        showToast("ペンネームを入力してください", "warning");
        return;
    }
    setPenName(name);
    document.getElementById("redpen-penname-step")?.classList.add("hidden");
    document.getElementById("redpen-form-step")?.classList.remove("hidden");
}

async function handleRedPenSubmit() {
    const toku = (document.getElementById("redpen-toku")?.value || "").trim();
    const kokoro = (document.getElementById("redpen-kokoro")?.value || "").trim();
    if (!toku || !kokoro) {
        showToast("添削後の「解き」と「その心は」を両方入力してください", "warning");
        return;
    }
    const submitBtn = document.getElementById("redpen-submit");
    if (submitBtn) submitBtn.disabled = true;
    try {
        await apiSubmitCorrection({
            originalDocId: redpenTargetDocId,
            clientUuid: appState.uid,
            penName: getPenName(),
            correctedToku: toku,
            correctedKokoro: kokoro,
        });
        await playHackerLogThenClose();
    } catch (e) {
        showToast(`添削の送信に失敗しました: ${e.message}`, "error");
    } finally {
        if (submitBtn) submitBtn.disabled = false;
    }
}

function initRedpenModal() {
    document.getElementById("redpen-close")?.addEventListener("click", closeRedpenModal);
    document.getElementById("redpen-penname-submit")?.addEventListener("click", handleRedPenPenNameSubmit);
    document.getElementById("redpen-submit")?.addEventListener("click", handleRedPenSubmit);
}

// ------------------------------------------------------------
// 初期化
// ------------------------------------------------------------

async function init() {
    document.getElementById("persona-chips")?.addEventListener("click", onPersonaChipsClick);
    document.getElementById("generate-form")?.addEventListener("submit", onGenerateSubmit);
    document.getElementById("timeline-list")?.addEventListener("click", onTimelineClick);
    document.getElementById("load-more-btn")?.addEventListener("click", loadMoreTimeline);
    document.getElementById("new-items-pill")?.addEventListener("click", flushPendingNewItems);
    initBlockScreen();
    initRedpenModal();

    try {
        appState.personas = await apiFetchPersonas();
        if (appState.personas.length) {
            appState.selectedPersonaId = appState.personas[0].persona_id;
        }
        renderPersonaChips();
    } catch (e) {
        showToast(`ペルソナ一覧の取得に失敗しました: ${e.message}`, "error");
    }

    await loadInitialTimeline();
    setInterval(pollForNewItems, NEW_ITEMS_POLL_MS);
}

init();
