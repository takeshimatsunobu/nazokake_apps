// frontend/ui/personas.js
// persona_feature_plan_v3.md Phase7: マイペルソナ管理画面(personas.html)のコントローラ。
//
// 【構成】
//   §8.1 一覧のセクション分離(マイペルソナ/アプリのペルソナ)
//   §8.2 編集モード(↑↓✎🗑ボタン、+ドラッグハンドルによるD&D並び替え)
//   §8.4 ツールチップ(title属性不使用、ボタン開閉式、GET /v1/personas/schemaから取得)
//   §8.5 ドラフト生成ボタンの連打防止
//
// 【今回の改修でD&D・長押し削除を追加した経緯】persona_feature_plan_v3.md §8.2は
// 「ジェスチャ判定・長押しタイマー・スクロール競合を避けるため」D&D/長押しを
// 意図的に不採用としていたが、改修要件で明示的にD&D並び替え・長押し削除が
// 求められたため、↑↓ボタン(キーボード・スクリーンリーダー用に維持)へ追加する形で
// 導入する。ドラッグハンドル・長押しはそれぞれ専用のタップ領域/移動許容量で
// 判定し、既存の①タップ操作(編集を開く・↑↓で並替)と衝突しないようにする。
import {
    apiFetchPersonas, apiFetchPersonaSchema, apiDraftPersona,
    apiCreatePersona, apiUpdatePersona, apiDeletePersona, apiReorderPersonas,
} from "api";
import { ensureAnonAuth } from "ui/auth";

const MAX_PERSONAS = 5; // api/routers/personas.py::MAX_PERSONAS_PER_OWNERと同じ値(表示用)
const LONG_PRESS_MS = 500;
const LONG_PRESS_MOVE_TOLERANCE_PX = 10;

let personas = [];
let schemaFields = [];
let editMode = false;

// ------------------------------------------------------------
// 小さなユーティリティ(apps/persona_main_function/frontend/app.js と同じ規約)
// ------------------------------------------------------------

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

function myPersonas(orderOverride) {
    const mine = personas.filter((p) => !p.is_builtin);
    if (!orderOverride) return mine;
    // D&Dのドラッグ中プレビュー用: orderOverride(persona_idの配列)の順序で並べ替える。
    const byId = new Map(mine.map((p) => [p.persona_id, p]));
    return orderOverride.map((id) => byId.get(id)).filter(Boolean);
}

function builtinPersonas() {
    return personas.filter((p) => p.is_builtin);
}

// ------------------------------------------------------------
// §8.1/§8.2: 一覧描画(セクション分離・編集モード)
// ------------------------------------------------------------

function myPersonaRowHtml(p, index, total) {
    if (!editMode) {
        // 通常モード: タップで編集/長押しで削除確認(§改修要件3、
        // attachLongPressDelegate参照)。削除ボタン自体は存在しないため、
        // 長押しを知らない・失敗したユーザーには誤爆しない(既存方針を維持)。
        return `<div data-persona-id="${escapeHtml(p.persona_id)}"
            class="persona-row flex items-center justify-between bg-white border border-slate-200 rounded-xl px-3 py-2.5">
            <button type="button" data-action="edit" class="flex-1 min-w-0 text-left text-sm font-bold text-slate-700 truncate">
                ${escapeHtml(p.display_name)}
            </button>
        </div>`;
    }
    // 編集モード: ↑↓✎🗑ボタン(キーボード・スクリーンリーダー用に維持)に加え、
    // ドラッグハンドル(⠿)でのD&D並び替えにも対応する。ハンドル・各ボタンは
    // data-no-longpress を付け、長押し削除の判定対象から除外する
    // (押している間ドラッグ/クリック操作と競合させないため)。
    return `<div data-persona-id="${escapeHtml(p.persona_id)}"
        class="persona-row flex items-center justify-between bg-white border border-indigo-200 rounded-xl px-3 py-2 gap-1.5">
        <span data-drag-handle data-no-longpress aria-label="ドラッグして並び替え"
            class="drag-handle shrink-0 w-7 h-8 flex items-center justify-center text-slate-400 text-base cursor-grab select-none">⠿</span>
        <span class="flex-1 min-w-0 text-sm font-bold text-slate-700 truncate">${escapeHtml(p.display_name)}</span>
        <div class="flex items-center gap-1 shrink-0">
            <button type="button" data-action="move-up" data-no-longpress ${index === 0 ? "disabled" : ""}
                aria-label="上へ移動"
                class="w-8 h-8 rounded-full border border-slate-300 text-slate-600 text-sm font-black disabled:opacity-30 disabled:pointer-events-none active:scale-95">↑</button>
            <button type="button" data-action="move-down" data-no-longpress ${index === total - 1 ? "disabled" : ""}
                aria-label="下へ移動"
                class="w-8 h-8 rounded-full border border-slate-300 text-slate-600 text-sm font-black disabled:opacity-30 disabled:pointer-events-none active:scale-95">↓</button>
            <button type="button" data-action="edit" data-no-longpress aria-label="編集"
                class="w-8 h-8 rounded-full border border-indigo-300 text-indigo-600 text-sm font-black active:scale-95">✎</button>
            <button type="button" data-action="delete" data-no-longpress aria-label="削除"
                class="w-8 h-8 rounded-full border border-rose-300 text-rose-600 text-sm font-black active:scale-95">🗑</button>
        </div>
    </div>`;
}

function renderMyPersonas(orderOverride) {
    const wrap = document.getElementById("my-personas-list");
    if (!wrap) return;
    const mine = myPersonas(orderOverride);
    if (!mine.length) {
        wrap.innerHTML = `<p class="text-center text-xs text-slate-400 py-6">まだマイペルソナがありません。下のボタンから作成できます。</p>`;
    } else {
        wrap.innerHTML = mine.map((p, i) => myPersonaRowHtml(p, i, mine.length)).join("");
    }
    updateCreateButtonState();
}

function renderBuiltinPersonas() {
    const wrap = document.getElementById("builtin-personas-list");
    if (!wrap) return;
    // §8.1: 組み込み10体は「編集トグルなし」の固定セクション。削除不可を示す
    // 🔒バッジを付け、長押ししても削除できないことを視覚的に明示する
    // (attachLongPressDelegateのonBuiltinLongPress参照)。
    wrap.innerHTML = builtinPersonas()
        .map(
            (p) => `<div data-persona-id="${escapeHtml(p.persona_id)}"
                class="bg-white border border-slate-200 rounded-xl px-3 py-2.5 flex items-center justify-between">
                <span class="text-sm text-slate-600">${escapeHtml(p.display_name)}</span>
                <span aria-label="削除不可" title="削除不可">🔒</span>
            </div>`
        )
        .join("");
}

function updateCreateButtonState() {
    const btn = document.getElementById("create-persona-btn");
    const note = document.getElementById("persona-limit-note");
    const count = myPersonas().length;
    const atLimit = count >= MAX_PERSONAS;
    if (btn) btn.disabled = atLimit;
    if (note) note.textContent = atLimit
        ? `マイペルソナは最大${MAX_PERSONAS}件までです`
        : `${count} / ${MAX_PERSONAS}件`;
}

function toggleEditMode() {
    editMode = !editMode;
    const btn = document.getElementById("edit-mode-toggle");
    if (btn) {
        btn.setAttribute("aria-pressed", String(editMode));
        btn.textContent = editMode ? "完了" : "編集";
    }
    renderMyPersonas();
}

async function loadPersonas() {
    try {
        personas = await apiFetchPersonas();
        renderMyPersonas();
        renderBuiltinPersonas();
    } catch (e) {
        showToast(`ペルソナ一覧の取得に失敗しました: ${e.message}`, "error");
    }
}

// ------------------------------------------------------------
// 並べ替え: ↑↓ボタン(隣接2件のsort_orderスワップを1リクエスト)
// ------------------------------------------------------------

async function handleMove(personaId, direction) {
    const mine = myPersonas();
    const idx = mine.findIndex((p) => p.persona_id === personaId);
    const targetIdx = idx + direction;
    if (idx < 0 || targetIdx < 0 || targetIdx >= mine.length) return;

    const swapped = [...mine];
    [swapped[idx], swapped[targetIdx]] = [swapped[targetIdx], swapped[idx]];
    const orderedIds = swapped.map((p) => p.persona_id);

    try {
        await apiReorderPersonas(orderedIds);
        await loadPersonas();
    } catch (e) {
        showToast(`並べ替えに失敗しました: ${e.message}`, "error");
    }
}

// ------------------------------------------------------------
// 並べ替え: ドラッグ&ドロップ(Pointer Events、マウス・タッチ・ペン共通)
//
// 【ポインタキャプチャの対象について】ドラッグ中はプレビューのため毎回
// renderMyPersonas()でリスト全体のinnerHTMLを再構築する。ドラッグハンドル
// (行の子要素)自体にsetPointerCaptureすると、その行が再描画で置き換わった
// 瞬間にキャプチャが失われる(要素がDOMツリーから外れるとブラウザが自動的に
// キャプチャを解放するため)。再描画されない親コンテナ(#my-personas-list)へ
// キャプチャすることでこの問題を避ける。
// ------------------------------------------------------------

let dragState = null; // { personaId, pointerId, order, rowHeight, listTop }

function startDrag(personaId, pointerId, listEl) {
    const rowEl = listEl.querySelector(`[data-persona-id="${personaId}"]`);
    if (!rowEl) return;
    listEl.setPointerCapture(pointerId);
    dragState = {
        personaId,
        pointerId,
        order: myPersonas().map((p) => p.persona_id),
        rowHeight: rowEl.getBoundingClientRect().height || 44,
        listTop: listEl.getBoundingClientRect().top,
    };
    markDraggingRow(listEl);
}

function markDraggingRow(listEl) {
    if (!dragState) return;
    const rowEl = listEl.querySelector(`[data-persona-id="${dragState.personaId}"]`);
    if (rowEl) rowEl.classList.add("opacity-60", "ring-2", "ring-indigo-400");
}

function updateDrag(ev, listEl) {
    if (!dragState || ev.pointerId !== dragState.pointerId) return;
    const relativeY = ev.clientY - dragState.listTop;
    const targetIndex = Math.max(
        0,
        Math.min(dragState.order.length - 1, Math.floor(relativeY / dragState.rowHeight))
    );
    const currentIndex = dragState.order.indexOf(dragState.personaId);
    if (targetIndex !== currentIndex && currentIndex !== -1) {
        dragState.order.splice(currentIndex, 1);
        dragState.order.splice(targetIndex, 0, dragState.personaId);
        renderMyPersonas(dragState.order);
        markDraggingRow(listEl);
    }
}

async function endDrag(ev, listEl) {
    if (!dragState || ev.pointerId !== dragState.pointerId) return;
    const { order, personaId, pointerId } = dragState;
    dragState = null;
    if (listEl.hasPointerCapture(pointerId)) listEl.releasePointerCapture(pointerId);
    const rowEl = listEl.querySelector(`[data-persona-id="${personaId}"]`);
    if (rowEl) rowEl.classList.remove("opacity-60", "ring-2", "ring-indigo-400");

    try {
        await apiReorderPersonas(order);
        await loadPersonas();
    } catch (e) {
        showToast(`並べ替えに失敗しました: ${e.message}`, "error");
        await loadPersonas(); // サーバー側の実際の順序へ復元する
    }
}

function onMyPersonasListPointerDown(ev) {
    if (!editMode) return;
    const handle = ev.target.closest("[data-drag-handle]");
    if (!handle) return;
    const row = handle.closest("[data-persona-id]");
    if (!row) return;
    ev.preventDefault();
    startDrag(row.dataset.personaId, ev.pointerId, ev.currentTarget);
}

function onMyPersonasListPointerMove(ev) {
    if (dragState) updateDrag(ev, ev.currentTarget);
}

function onMyPersonasListPointerEnd(ev) {
    if (dragState) endDrag(ev, ev.currentTarget);
}

// ------------------------------------------------------------
// §8.2: 削除(確認ダイアログを必ず挟む)
// ------------------------------------------------------------

async function handleDelete(personaId, displayName) {
    // 【§8.2/ユーザー指示4】削除には必ず確認ダイアログを挟む。通常モードでは
    // 削除ボタン自体が存在しないため誤爆しない(編集モード時のみこのボタンが描画される)。
    const confirmed = window.confirm(`「${displayName}」を削除しますか?この操作は取り消せません。`);
    if (!confirmed) return;

    try {
        await apiDeletePersona(personaId);
        showToast(`「${displayName}」を削除しました`, "info");
        await loadPersonas();
    } catch (e) {
        showToast(`削除に失敗しました: ${e.message}`, "error");
    }
}

// ------------------------------------------------------------
// 長押し削除(約500ms、移動許容量を超えたらキャンセル=スクロールと区別)
//
// マイペルソナ: 長押し確定時にバイブレーション→handleDelete()(確認ダイアログ
// 必須)を呼ぶ。ビルトイン: 削除不可であることを短長短のバイブレーションと
// トーストで伝える(is_deletable===falseのため実際にはAPIを呼ばない)。
// ------------------------------------------------------------

function triggerVibration(pattern) {
    if (typeof navigator !== "undefined" && typeof navigator.vibrate === "function") {
        try {
            navigator.vibrate(pattern);
        } catch (e) {
            // 非対応環境・ユーザー操作外での呼び出し拒否等は無視してよい
            // (削除確認フロー自体は続行できる)。
        }
    }
}

function attachLongPressDelegate(container, onLongPress) {
    if (!container) return;
    let timer = null;
    let startX = 0;
    let startY = 0;
    let activeRow = null;
    let firedForThisPress = false;

    function cancel() {
        if (timer) {
            clearTimeout(timer);
            timer = null;
        }
        activeRow = null;
    }

    container.addEventListener("pointerdown", (ev) => {
        if (ev.pointerType === "mouse" && ev.button !== 0) return;
        // ドラッグハンドル・↑↓✎🗑ボタン上からの押下は長押し判定の対象外にする
        // (それぞれの専用操作と競合させないため)。
        if (ev.target.closest("[data-no-longpress]")) return;
        const row = ev.target.closest("[data-persona-id]");
        if (!row) return;

        activeRow = row;
        startX = ev.clientX;
        startY = ev.clientY;
        firedForThisPress = false;
        timer = setTimeout(() => {
            firedForThisPress = true;
            timer = null;
            onLongPress(activeRow);
        }, LONG_PRESS_MS);
    });

    container.addEventListener("pointermove", (ev) => {
        if (!timer) return;
        const dx = Math.abs(ev.clientX - startX);
        const dy = Math.abs(ev.clientY - startY);
        if (dx > LONG_PRESS_MOVE_TOLERANCE_PX || dy > LONG_PRESS_MOVE_TOLERANCE_PX) {
            cancel(); // スクロール等の意図と判定し、長押しをキャンセルする
        }
    });

    ["pointerup", "pointercancel", "pointerleave"].forEach((type) => {
        container.addEventListener(type, cancel);
    });

    // 長押しが確定した直後に発火するclickイベント(edit等)を抑止する。
    container.addEventListener(
        "click",
        (ev) => {
            if (firedForThisPress) {
                ev.stopPropagation();
                ev.preventDefault();
                firedForThisPress = false;
            }
        },
        true
    );
}

function onMyPersonaLongPress(row) {
    const personaId = row.dataset.personaId;
    const persona = personas.find((p) => p.persona_id === personaId);
    if (!persona) return;
    triggerVibration(50);
    handleDelete(personaId, persona.display_name);
}

function onBuiltinPersonaLongPress() {
    // 短-長-短のパターンで「マイペルソナの単発振動」と区別できるようにする。
    triggerVibration([15, 60, 15]);
    showToast("🔒 アプリ標準のペルソナは削除できません", "warning");
}

// ------------------------------------------------------------
// 作成・編集フォーム
// ------------------------------------------------------------

let currentEditingId = null; // null = 新規作成

const DEFAULT_SETTINGS = {
    display_name: "",
    prompt: "",
    first_person: "",
    speech_style: "",
    tone: "gentle",
    favorite_topics: [],
    taboo: [],
    thinking_level: "low",
    temperature: 0.8,
};

function fillForm(settings) {
    const s = { ...DEFAULT_SETTINGS, ...(settings || {}) };
    document.getElementById("field-display_name").value = s.display_name || "";
    document.getElementById("field-prompt").value = s.prompt || "";
    document.getElementById("field-first_person").value = s.first_person || "";
    document.getElementById("field-speech_style").value = s.speech_style || "";
    document.getElementById("field-tone").value = s.tone || "gentle";
    document.getElementById("field-favorite_topics").value = (s.favorite_topics || []).join(", ");
    document.getElementById("field-taboo").value = (s.taboo || []).join(", ");
    document.getElementById("field-thinking_level").value = s.thinking_level || "low";
    document.getElementById("field-temperature").value = String(s.temperature ?? 0.8);
}

function readFormSettings() {
    const splitList = (value) =>
        value.split(",").map((s) => s.trim()).filter((s) => s.length > 0);

    return {
        display_name: document.getElementById("field-display_name").value.trim(),
        prompt: document.getElementById("field-prompt").value.trim(),
        first_person: document.getElementById("field-first_person").value.trim(),
        speech_style: document.getElementById("field-speech_style").value.trim(),
        tone: document.getElementById("field-tone").value,
        favorite_topics: splitList(document.getElementById("field-favorite_topics").value),
        taboo: splitList(document.getElementById("field-taboo").value),
        thinking_level: document.getElementById("field-thinking_level").value,
        temperature: Number(document.getElementById("field-temperature").value),
    };
}

function openCreateForm() {
    currentEditingId = null;
    document.getElementById("persona-form-title").textContent = "ペルソナを作る";
    fillForm(null);
    document.getElementById("persona-form-modal").classList.remove("hidden");
    document.getElementById("field-display_name").focus();
}

function openEditForm(persona) {
    currentEditingId = persona.persona_id;
    document.getElementById("persona-form-title").textContent = "ペルソナを編集";
    fillForm(persona.settings);
    document.getElementById("persona-form-modal").classList.remove("hidden");
}

function closeForm() {
    document.getElementById("persona-form-modal").classList.add("hidden");
    currentEditingId = null;
}

async function onFormSubmit(ev) {
    ev.preventDefault();
    const submitBtn = document.getElementById("persona-form-submit");
    const settings = readFormSettings();
    if (!settings.display_name || !settings.prompt) {
        showToast("呼び名と人格の説明は必須です", "warning");
        return;
    }

    submitBtn.disabled = true;
    try {
        if (currentEditingId) {
            await apiUpdatePersona(currentEditingId, settings);
            showToast("更新しました", "info");
        } else {
            await apiCreatePersona(settings);
            showToast("作成しました", "info");
        }
        closeForm();
        await loadPersonas();
    } catch (e) {
        showToast(`保存に失敗しました: ${e.message}`, "error");
    } finally {
        submitBtn.disabled = false;
    }
}

// ------------------------------------------------------------
// §7.4/§8.5: ドラフト生成(連打防止: ボタン無効化+スピナー表示)
// ------------------------------------------------------------

async function onDraftGenerateClick() {
    const displayName = document.getElementById("field-display_name").value.trim();
    if (!displayName) {
        showToast("先に呼び名を入力してください", "warning");
        return;
    }

    const btn = document.getElementById("draft-generate-btn");
    const spinner = document.getElementById("draft-spinner");
    const label = document.getElementById("draft-generate-label");
    // 【ユーザー指示6/§8.5】リクエスト送信中はボタンを無効化し、連打を防ぐ。
    btn.disabled = true;
    spinner.classList.remove("hidden");
    label.textContent = "生成中...";

    try {
        const res = await apiDraftPersona(displayName);
        fillForm(res.settings);
        if (res.is_fallback) {
            showToast("AI生成に失敗したため、空のひな形を入力しました。手動で編集してください。", "warning");
        } else {
            showToast("AIが下書きを作成しました。内容を確認・編集してください。", "info");
        }
    } catch (e) {
        showToast(`下書き生成に失敗しました: ${e.message}`, "error");
    } finally {
        btn.disabled = false;
        spinner.classList.add("hidden");
        label.textContent = "✨ AI下書き";
    }
}

// ------------------------------------------------------------
// §8.4: ツールチップ(title属性は使わない、ボタン開閉式、モバイルは下部シート)
// ------------------------------------------------------------

function schemaTooltipText(fieldKey) {
    const field = schemaFields.find((f) => f.key === fieldKey);
    return field ? field.tooltip : "";
}

function openTooltip(fieldKey, triggerBtn) {
    const overlay = document.getElementById("tooltip-overlay");
    const title = document.getElementById("tooltip-sheet-title");
    const body = document.getElementById("tooltip-sheet-body");
    if (!overlay || !title || !body) return;

    title.textContent = triggerBtn.closest("div")?.querySelector("label")?.textContent || fieldKey;
    body.textContent = schemaTooltipText(fieldKey) || "説明はありません。";
    overlay.classList.remove("hidden");
    overlay.dataset.openTrigger = fieldKey;
    document.querySelectorAll(".tooltip-trigger").forEach((b) => b.setAttribute("aria-expanded", "false"));
    triggerBtn.setAttribute("aria-expanded", "true");
}

function closeTooltip() {
    document.getElementById("tooltip-overlay")?.classList.add("hidden");
    document.querySelectorAll(".tooltip-trigger").forEach((b) => b.setAttribute("aria-expanded", "false"));
}

async function loadSchema() {
    try {
        schemaFields = await apiFetchPersonaSchema();
    } catch (e) {
        // ツールチップの説明文が取れないだけなので、致命的エラーにはしない
        // (フォーム自体は引き続き使える)。
        console.warn("ペルソナ設定スキーマの取得に失敗:", e);
        schemaFields = [];
    }
}

// ------------------------------------------------------------
// イベント委譲・初期化
// ------------------------------------------------------------

function onMyPersonasListClick(ev) {
    const row = ev.target.closest("[data-persona-id]");
    if (!row) return;
    const personaId = row.dataset.personaId;
    const persona = personas.find((p) => p.persona_id === personaId);
    if (!persona) return;

    const actionBtn = ev.target.closest("[data-action]");
    if (!actionBtn) return;
    const action = actionBtn.dataset.action;

    if (action === "edit") {
        openEditForm(persona);
    } else if (action === "delete") {
        handleDelete(personaId, persona.display_name);
    } else if (action === "move-up") {
        handleMove(personaId, -1);
    } else if (action === "move-down") {
        handleMove(personaId, 1);
    }
}

async function init() {
    document.getElementById("edit-mode-toggle")?.addEventListener("click", toggleEditMode);
    const myPersonasList = document.getElementById("my-personas-list");
    myPersonasList?.addEventListener("click", onMyPersonasListClick);
    myPersonasList?.addEventListener("pointerdown", onMyPersonasListPointerDown);
    myPersonasList?.addEventListener("pointermove", onMyPersonasListPointerMove);
    myPersonasList?.addEventListener("pointerup", onMyPersonasListPointerEnd);
    myPersonasList?.addEventListener("pointercancel", onMyPersonasListPointerEnd);
    attachLongPressDelegate(myPersonasList, onMyPersonaLongPress);
    attachLongPressDelegate(document.getElementById("builtin-personas-list"), onBuiltinPersonaLongPress);
    document.getElementById("create-persona-btn")?.addEventListener("click", openCreateForm);
    document.getElementById("persona-form-close")?.addEventListener("click", closeForm);
    document.getElementById("persona-form")?.addEventListener("submit", onFormSubmit);
    document.getElementById("draft-generate-btn")?.addEventListener("click", onDraftGenerateClick);
    document.getElementById("tooltip-close")?.addEventListener("click", closeTooltip);
    document.getElementById("tooltip-overlay")?.addEventListener("click", (ev) => {
        if (ev.target.id === "tooltip-overlay") closeTooltip(); // 背景クリックで閉じる
    });
    document.querySelectorAll(".tooltip-trigger").forEach((btn) => {
        btn.addEventListener("click", () => openTooltip(btn.dataset.tooltipField, btn));
    });

    try {
        await ensureAnonAuth();
    } catch (e) {
        showToast("認証に失敗しました。ページを再読み込みしてください。", "error");
        return;
    }

    await Promise.all([loadPersonas(), loadSchema()]);
}

init();
