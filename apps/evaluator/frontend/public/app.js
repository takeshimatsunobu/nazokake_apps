// @ts-nocheck -- 未移行(段階的にJSDoc型付けを進める対象。window.*グローバル多用のため一括除外)
import { ensureAnonAuth, auth } from "ui/auth";
ensureAnonAuth().catch(err => console.error("認証初期化エラー:", err));

import { APP_URL } from "config";
import { appState } from "state";
import {
    apiLogEvent, apiGenerate, apiGetStatus, apiSubmitHumanRiddle, apiFetchFeed, apiSubmitFeedEvaluation,
    apiSubmitFeedback, apiFetchBoard, apiPostBoard, apiFetchPersonas, apiFetchPopularPersonas,
    apiDraftPersona, apiCreatePersona,
} from "api";
import { uiSwitchTab } from "ui/tabs";
import {
    uiGenReset, uiGenLoadingStart, uiGenLoadingStop, uiRenderGenResult, uiShowResult,
    uiMarkGenPollFailed, setSubmitModelRatingHandler,
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

// ============================================================
// 【改修要件: トップ画面へのペルソナUI統合】カテゴリ切替ピルタブ(公式/マイ
// ペルソナ/人気)+水平スクロールチップ+作成モーダル。旧<select>ベースUIを
// 置き換える。実際に生成へ渡すpersona_idは非表示input(#persona)に保持し、
// startGeneration()側の変更を最小化する。
// ============================================================

function escapeHtml(s) {
    return String(s == null ? "" : s)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

const PERSONA_TONE_LABELS = {
    gentle: "おだやか", energetic: "元気いっぱい", cool: "クール", warm: "あたたかい",
    sharp: "辛口", playful: "おちゃめ", serious: "まじめ",
};

const BUILTIN_PERSONAS = [
    { persona_id: "1", display_name: "1. 昭和生まれの天才漫才師" },
    { persona_id: "2", display_name: "2. 辞書の編纂者" },
    { persona_id: "3", display_name: "3. アジア系ITエンジニア" },
    { persona_id: "4", display_name: "4. 大阪のおばちゃん" },
    { persona_id: "5", display_name: "5. 理屈っぽい中学2年生男子" },
    { persona_id: "6", display_name: "6. 超ポジティブな高2ギャル" },
    { persona_id: "7", display_name: "7. マニアックな大学生" },
    { persona_id: "8", display_name: "8. 人間観察が趣味の女子大生" },
    { persona_id: "9", display_name: "9. 社会の不条理に揉まれる若手OL" },
    { persona_id: "10", display_name: "10. 横文字だらけの中年起業家" },
];

const _personaCache = { builtin: BUILTIN_PERSONAS, mine: [], popular: [] };
let _personaCategory = 'builtin';
let _selectedPersona = { persona_id: "1", display_name: BUILTIN_PERSONAS[0].display_name, tone: "", first_person: "" };

function personaToneLabel(tone) {
    return PERSONA_TONE_LABELS[tone] || tone || "";
}

function renderPersonaPreview() {
    const el = document.getElementById('persona-preview');
    if (!el) return;
    const toneLabel = personaToneLabel(_selectedPersona.tone);
    const parts = [];
    if (toneLabel) parts.push(`雰囲気: ${toneLabel}`);
    if (_selectedPersona.first_person) parts.push(`一人称: 「${_selectedPersona.first_person}」`);
    if (!parts.length) {
        el.classList.add('hidden');
        el.textContent = '';
        return;
    }
    el.textContent = `🎭 ${_selectedPersona.display_name} — ${parts.join(' / ')}`;
    el.classList.remove('hidden');
}

function selectPersona(persona) {
    _selectedPersona = persona;
    const input = document.getElementById('persona');
    if (input) input.value = String(persona.persona_id);
    renderPersonaChips();
    renderPersonaPreview();
}

function renderPersonaChips() {
    const scroll = document.getElementById('persona-chip-scroll');
    if (!scroll) return;
    const items = _personaCache[_personaCategory] || [];
    const createChipHtml = `<button type="button" id="persona-create-chip" class="persona-chip shrink-0 whitespace-nowrap text-xs font-bold px-3 py-1.5 rounded-full border-2 border-dashed border-[#902A19]/40 text-[#902A19]">➕ 新規作成</button>`;

    if (!items.length) {
        const emptyLabel = _personaCategory === 'mine' ? 'まだマイペルソナがありません' : '該当するペルソナがありません';
        scroll.innerHTML = createChipHtml + `<p class="text-xs text-gray-400 py-1.5 shrink-0 whitespace-nowrap">${emptyLabel}</p>`;
        return;
    }

    const chipsHtml = items.map((p) => {
        const active = String(p.persona_id) === String(_selectedPersona.persona_id);
        const cls = active ? 'bg-[#902A19] text-white border-[#902A19]' : 'bg-white text-gray-700 border-gray-300';
        const label = p.display_name || p.name || `ペルソナ#${p.persona_id}`;
        return `<button type="button" data-persona-id="${escapeHtml(p.persona_id)}" class="persona-chip shrink-0 whitespace-nowrap text-xs font-bold px-3 py-1.5 rounded-full border ${cls}">${escapeHtml(label)}</button>`;
    }).join('');

    scroll.innerHTML = createChipHtml + chipsHtml;
}

function setActiveCategoryTab(category) {
    document.querySelectorAll('.persona-category-tab').forEach((btn) => {
        const active = btn.dataset.category === category;
        btn.classList.toggle('bg-[#902A19]', active);
        btn.classList.toggle('text-white', active);
        btn.classList.toggle('bg-gray-100', !active);
        btn.classList.toggle('text-gray-600', !active);
        btn.setAttribute('aria-selected', String(active));
    });
}

function switchPersonaCategory(category) {
    _personaCategory = category;
    setActiveCategoryTab(category);
    renderPersonaChips();
}

function onPersonaChipScrollClick(ev) {
    const createChip = ev.target.closest('#persona-create-chip');
    if (createChip) {
        openPersonaCreateModal();
        return;
    }
    const chip = ev.target.closest('[data-persona-id]');
    if (!chip) return;
    const source = _personaCache[_personaCategory] || [];
    const persona = source.find((p) => String(p.persona_id) === chip.dataset.personaId);
    if (!persona) return;
    selectPersona({
        persona_id: persona.persona_id,
        display_name: persona.display_name || persona.name,
        tone: persona.tone || '',
        first_person: persona.first_person || '',
    });
}

// ①マイペルソナ(GET /v1/personas、認証必須): 匿名認証は既にモジュール読み込み
// 時点でensureAnonAuth()が開始済み(app.js冒頭)のため、ここでは完了を待つのみ。
async function loadMyPersonas() {
    try {
        const idToken = (auth && auth.currentUser) ? await auth.currentUser.getIdToken() : await ensureAnonAuth();
        const personas = await apiFetchPersonas(idToken);
        _personaCache.mine = (personas || []).filter((p) => !p.is_builtin);
    } catch (e) {
        console.warn("マイペルソナの取得に失敗しました(スキップします):", e);
    }
}

// ②みんなのペルソナ(GET /v1/personas/popular、認証不要)
async function loadPopularPersonas() {
    try {
        _personaCache.popular = await apiFetchPopularPersonas(10) || [];
    } catch (e) {
        console.warn("みんなのペルソナの取得に失敗しました(スキップします):", e);
    }
}

export async function loadPersonaOptions() {
    renderPersonaChips();
    renderPersonaPreview();
    setActiveCategoryTab(_personaCategory);

    document.getElementById('persona-chip-scroll')?.addEventListener('click', onPersonaChipScrollClick);
    document.querySelectorAll('.persona-category-tab').forEach((btn) => {
        btn.addEventListener('click', () => switchPersonaCategory(btn.dataset.category));
    });
    initPersonaCreateModal();

    // 【ディープ監査#5と同じ方針】マイペルソナ(認証必須)取得の遅延が、無関係な
    // みんなのペルソナ(認証不要)の表示をブロックしないよう独立並行させる。
    await Promise.allSettled([loadMyPersonas(), loadPopularPersonas()]);
    renderPersonaChips();
}

// ------------------------------------------------------------
// 【改修要件】ペルソナ作成スライドインモーダル(画面遷移なし)。
// 「✨ Geminiにおまかせドラフト生成」→ 微調整 → 「保存してこのペルソナを選択」
// で、モーダルを閉じ即座に選択状態へ反映する。
// ------------------------------------------------------------

function openPersonaCreateModal() {
    const modal = document.getElementById('persona-create-modal');
    if (!modal) return;
    document.getElementById('persona-create-keyword').value = '';
    document.getElementById('persona-create-name').value = '';
    document.getElementById('persona-create-prompt').value = '';
    document.getElementById('persona-create-first-person').value = '';
    document.getElementById('persona-create-tone').value = 'gentle';
    modal.classList.remove('hidden');
}

function closePersonaCreateModal() {
    document.getElementById('persona-create-modal')?.classList.add('hidden');
}

async function onPersonaCreateDraftClick() {
    const keyword = document.getElementById('persona-create-keyword')?.value.trim();
    if (!keyword) {
        showToast('キーワードを入力してください', 'warning');
        return;
    }
    const btn = document.getElementById('persona-create-draft-btn');
    const spinner = document.getElementById('persona-create-draft-spinner');
    const label = document.getElementById('persona-create-draft-label');
    btn.disabled = true;
    spinner?.classList.remove('hidden');
    if (label) label.textContent = '生成中...';
    try {
        const idToken = (auth && auth.currentUser) ? await auth.currentUser.getIdToken() : await ensureAnonAuth();
        const res = await apiDraftPersona(idToken, keyword);
        const s = res.settings || {};
        document.getElementById('persona-create-name').value = s.display_name || keyword;
        document.getElementById('persona-create-prompt').value = s.prompt || '';
        document.getElementById('persona-create-first-person').value = s.first_person || '';
        document.getElementById('persona-create-tone').value = s.tone || 'gentle';
        showToast(res.is_fallback ? 'AI生成に失敗したため空のひな形を入力しました' : 'AIが下書きを作成しました', res.is_fallback ? 'warning' : 'success');
    } catch (e) {
        showToast(`下書き生成に失敗しました: ${e.message}`, 'warning');
    } finally {
        btn.disabled = false;
        spinner?.classList.add('hidden');
        if (label) label.textContent = '✨ Geminiにおまかせ';
    }
}

async function onPersonaCreateSaveClick() {
    const displayName = document.getElementById('persona-create-name')?.value.trim();
    const prompt = document.getElementById('persona-create-prompt')?.value.trim();
    const firstPerson = document.getElementById('persona-create-first-person')?.value.trim();
    const tone = document.getElementById('persona-create-tone')?.value || 'gentle';
    if (!displayName || !prompt) {
        showToast('呼び名と人格の説明は必須です', 'warning');
        return;
    }
    const btn = document.getElementById('persona-create-save-btn');
    btn.disabled = true;
    try {
        const idToken = (auth && auth.currentUser) ? await auth.currentUser.getIdToken() : await ensureAnonAuth();
        const settings = { display_name: displayName, prompt, first_person: firstPerson, tone };
        const res = await apiCreatePersona(idToken, settings);
        const newPersona = { persona_id: res.persona_id, display_name: displayName, tone, first_person: firstPerson, is_builtin: false };
        _personaCache.mine = [newPersona, ..._personaCache.mine];
        closePersonaCreateModal();
        switchPersonaCategory('mine');
        selectPersona(newPersona);
        showToast(`「${displayName}」を作成し、選択しました`, 'success');
    } catch (e) {
        showToast(`作成に失敗しました: ${e.message}`, 'warning');
    } finally {
        btn.disabled = false;
    }
}

function initPersonaCreateModal() {
    document.getElementById('persona-create-close')?.addEventListener('click', closePersonaCreateModal);
    document.getElementById('persona-create-modal')?.addEventListener('click', (ev) => {
        if (ev.target.id === 'persona-create-modal') closePersonaCreateModal(); // 背景クリックで閉じる
    });
    document.getElementById('persona-create-draft-btn')?.addEventListener('click', onPersonaCreateDraftClick);
    document.getElementById('persona-create-save-btn')?.addEventListener('click', onPersonaCreateSaveClick);
}

export async function startGeneration() {
    const odai = document.getElementById('odaiInput')?.value.trim(); if (!odai) { showError("お題を入力してください！"); return; }
    // 【2026-08-16改修】マイペルソナ/みんなのペルソナはUUID文字列のIDを持つため、
    // parseIntすると壊れる(NaN)。ビルトイン("1"〜"10")も含め、常に文字列の
    // ままpersona_idとして送信する(バックエンドはint|str両対応、str化済み)。
    // 【改修要件: チップUI統合】"＋新規作成"は独立したチップ(#persona-create-chip)
    // でありselectPersona()経由でこのinputへ値が入ることは無いため、旧<select>
    // 時代のセンチネル値ガードは不要になった(作成はモーダル内で完結する)。
    const personaId = document.getElementById('persona')?.value || "1";
    const temperature = parseFloat(document.getElementById('temperature')?.value) || 0.6;
    // UI制御（前回結果のクリア＋ローディング開始）は ui/result.js に委譲。
    uiGenReset();
    uiGenLoadingStart();
    logEvent('generate_requested');
    try {
        const data = await apiGenerate(odai, personaId, temperature);
        if (!data?.task_id) {
            showError("生成タスクの開始に失敗しました(task_idが取得できませんでした)");
            return;
        }
        // ローカルGPU(ELYZA)が停止・暴走していても無限ロードにならないよう、
        // ポーリング開始時点を起点にタイムアウトを持たせる。
        // 【実機計測に基づく調整】本番はCloud Run→Firestoreジョブ作成→ローカル
        // ワーカーのポーリング検知(最大8秒、workers/ondemand_elyza_worker.py)→
        // 生成→Firestore書き戻し→Cloud Runの再ポーリングという往復になり、直結経路
        // (ローカル開発)だけでもELYZA側の完走に42秒程度かかることを実測済み。
        // 旧来の60秒だと本番の現実的な往復時間に対して余裕が無く、正常に完走する
        // はずのジョブまでタイムアウトしてGemini単独表示へ縮退していた。
        // 【ディープ監査#7】ローカル直接生成パス(K_SERVICE未設定)のELYZA呼び出しは
        // services/generation.pyでhttpx.Timeout(120.0, connect=5.0)まで待つ設計
        // のため、旧来の90秒だとバックエンドがまだ処理中でも先にクライアント側が
        // 「タイムアウト」表示へ倒れてしまうケースがあった(データ自体は失われず
        // リロードで見えるが、UX上は誤ったタイムアウト表示になる)。バックエンドの
        // 最大待機時間(120秒)に安全マージンを足した150秒へ揃える。
        // 【採点中スピナー固着調査】このtaskIdを「現在アクティブな生成」として記録する。
        // 以前の生成が未完了のままここに到達した場合、その古いtaskId向けの
        // pollStatus()ループは次回のポーリングチェックで自己終了する。
        _activeGenTaskId = data.task_id;
        pollStatus(data.task_id, Date.now() + 150000);
    } catch (e) { showError(e.message); }
}
// 段階開示ポーリング。本文が出た時点(gemini_generated)からデュアルカードを描画し、
// 状態が進むたび(gemini_completed → all_completed)に冪等に再描画する。
//  - gemini_generated : Gemini 本文のみ表示・評価欄は「🔍 分析官が採点中...」
//  - gemini_completed : Gemini にスコア付与（ELYZA は生成/採点中）
//  - all_completed    : ELYZA も出揃い完了（'completed' は旧データ互換）
//
// 【instructions/286】バックエンドのアーキテクチャ変更により、Gemini側の全体
// status が先に 'all_completed' へ到達し、ELYZAの推論(オンデマンドジョブキュー
// 経由の elyza_job_status、またはローカル直接生成パスの llmjp_status)が後から
// 非同期に完了するようになった。overall status のみでポーリングを止めると、
// 後から届くELYZA結果を永遠に受け取れなくなる(画面が採点中表示のまま固まる)。
// ELYZA側は経路によって完了シグナルが異なる(オンデマンドキュー経由なら
// elyza_job_status、ローカル直接生成パスなら llmjp_status)ため、どちらか一方が
// 終端状態に達していれば良いとする(片方しか更新されない経路が存在するため)。
const ELYZA_JOB_TERMINAL_STATUSES = ['completed', 'failed', 'dead_letter'];
const LLMJP_TERMINAL_STATUSES = ['completed', 'failed', 'none'];
function isElyzaSideDone(data) {
    if (data.elyza_job_status == null || ELYZA_JOB_TERMINAL_STATUSES.includes(data.elyza_job_status)) return true;
    return LLMJP_TERMINAL_STATUSES.includes(data.llmjp_status);
}
// タスクごとに一度だけタイムアウトアラートを出すためのガード。
const _timedOutTasks = new Set();

// 【採点中スピナー固着調査(2026-08-18)】現在アクティブな(=最後にstartGeneration()が
// 発火した)taskId。ユーザーが前回生成の完了を待たずに「別のお題で作る」→再生成した
// 場合、古いtaskId向けのpollStatus()ループが取り残されて動き続け、新しいカードの
// 描画結果を古いデータで上書きし続けるレース(実機テストで最大数秒の表示チラつきを
// 確認済み)があった。以後のpollStatus呼び出しはこの値と一致する場合のみ描画・
// 再スケジュールし、一致しなければ静かに自己終了する。
let _activeGenTaskId = null;

// deadline: このタスクのポーリングを打ち切る絶対時刻(ms epoch、呼び出し元で90秒後に
// 設定)。ローカルGPU(ELYZA)が停止・暴走して応答が返らない場合でも、期限が来たら
// ポーリングを諦めてGeminiの結果のみを画面に確定表示する(無限ロード防止のフォールバック)。
async function pollStatus(taskId, deadline) {
    if (taskId !== _activeGenTaskId) return; // 別の生成に取って代わられた古いポーリングは即終了
    try {
        const data = await apiGetStatus(taskId);
        if (taskId !== _activeGenTaskId) return; // await中に新しい生成が始まっていた場合も同様
        if (data.status === 'error' || data.eval_status === 'error') { throw new Error(data.message || "エラー"); }
        const shown = ['gemini_generated', 'gemini_completed', 'all_completed', 'completed'].includes(data.status);
        if (shown) {
            uiGenLoadingStop();
            // 【採点中スピナー固着調査】描画自体(DOM操作)で予期しない例外が起きても
            // ポーリングループそのものは継続させる。ここで例外が伝播すると、直後の
            // catchがuiMarkGenPollFailed+showErrorでポーリングを完全に打ち切ってしまい、
            // 次回以降届くはずの正常なデータ(採点結果等)を永久に受け取れなくなる
            // (スピナーが固まって見える一因になり得るため、1回の描画失敗ではループを
            // 諦めない設計にする)。
            try {
                uiRenderGenResult(data, taskId);
            } catch (renderErr) {
                console.error("結果描画中にエラーが発生しました(ポーリングは継続します):", renderErr);
            }
        }
        const overallDone = data.status === 'all_completed' || data.status === 'completed';
        if (overallDone && isElyzaSideDone(data)) { return; } // 全完了（Gemini・ELYZA双方）。ポーリング終了
        if (deadline && Date.now() >= deadline) {
            if (!_timedOutTasks.has(taskId)) {
                _timedOutTasks.add(taskId);
                uiGenLoadingStop();
                alert("ローカルGPU(ELYZA)からの応答がタイムアウトしました。Geminiの結果のみ表示します。");
                uiMarkGenPollFailed(taskId); // 未着のELYZAカードをフォールバック表示へ倒す
            }
            return; // これ以上ポーリングしない
        }
        setTimeout(() => pollStatus(taskId, deadline), 2000);
    } catch (e) {
        // 【instructions/289】ポーリングが例外(Fetch通信エラー、または上のstatus==='error'
        // 判定による明示的throw)で中断した場合、トップレベルのローディング解除(showError内)
        // だけでなく、まだ「生成中/採点中」スピナーを表示している個別カード(Gemini/ELYZA)も
        // フォールバック表示へ遷移させる。
        uiMarkGenPollFailed(taskId);
        showError(e.message);
    }
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
/* [SRE Disabled] 
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
*/

