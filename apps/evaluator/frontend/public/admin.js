import { firebaseConfig } from "firebase-config";
import { API_BASE } from "config";
import { uiSwitchTab } from "ui/tabs";

// 【Phase 0】招待URL(?invite=<token>)のトークンをsessionStorageへ退避しておく
// キー。ログイン前(FirebaseUIのリダイレクト/ポップアップを挟む可能性がある)の
// タイミングでURLパラメータを読んでおき、ログイン完了後にredeemへ使う。
const INVITE_TOKEN_STORAGE_KEY = "nazo_admin_invite_token";

// 【Phase1】お知らせバッジの基準時刻(action-required-summaryが返す
// previous_login_at)。DLQ/承認待ちデータ/承認待ち管理者の各render関数が
// 「🆕新着」判定に使うため、モジュールスコープに保持する(loadActionRequiredSummary()
// が initAdmin() の最初に他のload*()より先にawaitされ、この値を確定させてから
// 各リストの描画が走る前提)。
let _previousLoginAt = null;

// 【Phase1】アイテムのタイムスタンプが_previousLoginAtより新しければ「🆕」バッジの
// HTMLを返す(古い/不明なら空文字)。ISO8601文字列同士の比較は同一タイムゾーン
// (UTC)である限り文字列の辞書式比較でも安全だが、ここでは明示的にDateへ変換して
// 比較する(タイムゾーン表記の揺れに強くするため)。
function _isNewSince(timestampIso) {
    if (!_previousLoginAt || !timestampIso) return false;
    const t = new Date(timestampIso).getTime();
    const prev = new Date(_previousLoginAt).getTime();
    if (Number.isNaN(t) || Number.isNaN(prev)) return false;
    return t > prev;
}

// 【persona_feature_plan_v3.md Phase2】評価軸コード→表示ラベル。
// apps/evaluator/backend/services/evaluation.pyのAXES(11軸)と対応させる
// (persona_router/frontend側のresult.jsのuiAxisLabelsと同じ役割)。
// Few-shot採用時の評価軸タグ選択に使う。
const AXIS_LABELS = {
    S_nat: '自然さ', S_tech: '技巧', S_rhy: 'リズム', S_prosody: '韻律',
    S_sur: '意外性', S_emo: '論理/納得感', S_cultural: '文化',
    S_visual: '視覚', S_sensory: '感覚', S_cm: 'クロスモーダル', S_ontology: '存在論',
};

// 【Phase5/6】nazokake_items.origin_type → バッジ表示。承認待ちキューの各行が
// どのユーザーアクション由来か(AI生成/道場破りの赤ペン/自作投稿)を一目で示す。
const ORIGIN_TYPE_BADGES = {
    ai_generated: { emoji: '🤖', label: 'AI生成', className: 'bg-slate-100 text-slate-600 border-slate-200' },
    user_akapen: { emoji: '🖍️', label: '赤ペン添削', className: 'bg-orange-50 text-orange-700 border-orange-200' },
    user_original: { emoji: '💡', label: '自作投稿', className: 'bg-purple-50 text-purple-700 border-purple-200' },
};

function _originTypeBadgeHtml(originType) {
    const badge = ORIGIN_TYPE_BADGES[originType] || ORIGIN_TYPE_BADGES.ai_generated;
    return `<span class="inline-block text-[10px] font-bold ${badge.className} border rounded-full px-2 py-0.5 ml-1 align-middle">${badge.emoji} ${badge.label}</span>`;
}

function _newBadgeHtml(timestampIso) {
    return _isNewSince(timestampIso)
        ? '<span class="inline-block text-[10px] font-black bg-rose-600 text-white rounded-full px-1.5 py-0.5 ml-1">🆕 新着</span>'
        : '';
}

function showToast(msg, type='info') {
    const container = document.getElementById('toast-container'); if(!container) return;
    const toast = document.createElement('div');
    toast.className = `bg-[#902A19] text-white px-6 py-3 rounded-full shadow-lg mb-2 text-sm font-bold transition-all duration-300 transform translate-y-0 opacity-100 z-50`;
    toast.innerText = msg;
    container.appendChild(toast);
    setTimeout(() => { toast.classList.add('opacity-0', '-translate-y-2'); setTimeout(() => toast.remove(), 300); }, 3000);
}

// 🔐 Firebase(compat SDK)の初期化。FirebaseUI 6.1.0にESM版が存在しないため、
// Firebase Auth自体もcompatのグローバル`firebase`のまま維持する(admin.html側の
// <script>タグでfirebase-app-compat.js/firebase-auth-compat.js/firebase-ui-authを
// クラシック読み込みしている前提)。
if (typeof firebase !== 'undefined' && firebaseConfig && !firebase.apps.length) {
    firebase.initializeApp(firebaseConfig);
}

// 🔥 FirebaseUI の初期化
const ui = new firebaseui.auth.AuthUI(firebase.auth());

const uiConfig = {
    callbacks: {
        signInSuccessWithAuthResult: function(authResult, redirectUrl) {
            showToast("認証成功しました！");
            return false; // リダイレクトさせない
        },
        uiShown: function() {
        }
    },
    signInFlow: 'popup',
    signInOptions: [
        firebase.auth.GoogleAuthProvider.PROVIDER_ID
    ],
    tosUrl: '<your-tos-url>',
    privacyPolicyUrl: '<your-privacy-policy-url>'
};

// 【Phase 0】ページ読み込み時点でURLに?invite=<token>があれば、ログイン前に
// sessionStorageへ退避しておく(FirebaseUIのポップアップサインインでも同一ページ
// のままなので必須ではないが、将来リダイレクト方式に変えても壊れないようにする
// 防御的な実装)。
(function stashInviteTokenFromUrl() {
    const params = new URLSearchParams(window.location.search);
    const token = params.get('invite');
    if (token) sessionStorage.setItem(INVITE_TOKEN_STORAGE_KEY, token);
})();

function _clearInviteTokenFromUrl() {
    const url = new URL(window.location.href);
    if (!url.searchParams.has('invite')) return;
    url.searchParams.delete('invite');
    window.history.replaceState({}, '', url.toString());
}

// 招待トークンをredeemする(ログイン直後に1回だけ呼ばれる)。成功/失敗いずれの
// 場合も呼び出し元でsessionStorageのトークンを消費済みとして扱う(1回限りの
// リダイーム試行。失敗時に無限リトライしない)。
async function _redeemInviteIfPresent() {
    const token = sessionStorage.getItem(INVITE_TOKEN_STORAGE_KEY);
    if (!token) return;
    sessionStorage.removeItem(INVITE_TOKEN_STORAGE_KEY);
    _clearInviteTokenFromUrl();
    try {
        const res = await authFetch(`${API_BASE}/admin/invites/redeem`, {
            method: 'POST',
            body: JSON.stringify({ token }),
        });
        showToast(res.message || "招待を確認しました");
    } catch (e) {
        showToast(`招待の確認に失敗しました: ${e.message}`, "warning");
    }
}

// verify_admin_token拡張(承認チェック)に実際に通るかどうかを、既存の軽量な
// GETエンドポイント(監査証跡)を叩いて確認する。専用のwhoamiエンドポイントを
// 新設せず、既にDeps(verify_admin_token)を要求している既存APIを流用することで
// バックエンドの変更を最小限にする。
//
// 【障害調査で判明した設計ミスの修正】以前はここで「403以外は例外として
// 再送出」していたが、呼び出し元(onAuthStateChanged)側はその例外を
// catch(e){ return; } と黙って握りつぶすだけで、どの画面(login/pending/admin)
// も表示しないまま終了していた。CORSでpreflightがブロックされた場合、
// fetch()自体がHTTPステータスを持たない TypeError("Failed to fetch") を投げる
// ため、この経路を通り「白画面」になっていた(今回の実際の障害の直接原因)。
// 状態を3値("approved"/"denied"/"network_error")の戻り値にして、呼び出し元が
// 必ずどれか1つの画面を出せるようにする(例外を投げない=呼び出し元でtry/catch
// 漏れが起きようがない設計にする)。
async function _checkAdminAccess() {
    try {
        await authFetch(`${API_BASE}/admin/audit_logs`);
        return "approved";
    } catch (e) {
        if (String(e.message).includes('403')) return "denied";
        // 401(認証切れ)はauthFetch内で既にlogout()がトリガーされ、
        // onAuthStateChangedがuser=nullで再度firedされるので、ここでは
        // network_error扱いにしても実害はない(すぐにログイン画面へ遷移する)。
        console.error("🚨 [Admin Access Check] 通信エラー:", e);
        return "network_error";
    }
}

function _showPendingApprovalScreen(message) {
    const pendingScreen = document.getElementById('pending-approval-screen');
    const messageEl = document.getElementById('pending-approval-message');
    if (messageEl && message) messageEl.textContent = message;
    pendingScreen?.classList.remove('hidden');
}

// 🔐 Firebase Auth 状態の監視
firebase.auth().onAuthStateChanged(async (user) => {
    const loginScreen = document.getElementById('login-screen');
    const pendingScreen = document.getElementById('pending-approval-screen');
    const adminScreen = document.getElementById('admin-screen');

    if (user) {
        if (loginScreen) loginScreen.style.display = 'none';
        // 【絶対制約】ここから先、何が起きても最終的に必ずいずれか1画面を
        // 表示する(pendingScreen/adminScreenのどちらも出さない「白画面」状態を
        // 構造的に作らない)。
        pendingScreen?.classList.add('hidden');
        adminScreen?.classList.add('hidden');

        await _redeemInviteIfPresent();

        const accessState = await _checkAdminAccess();

        if (accessState === "approved") {
            adminScreen?.classList.remove('hidden');
            initAdmin();
        } else if (accessState === "denied") {
            _showPendingApprovalScreen(
                "このアカウントはまだ管理コクピットへのアクセスが許可されていません。" +
                "招待メールのリンクからアクセスした場合は、メイン管理者の承認をお待ちください。"
            );
        } else {
            // network_error: CORS設定漏れ・バックエンド未起動・ネットワーク断等。
            // 「アクセス権が無い」と誤解させないよう、明確に別文言で通知する。
            showToast("バックエンドとの通信に失敗しました(CORS設定またはネットワークを確認してください)", "warning");
            _showPendingApprovalScreen(
                "バックエンドと通信できませんでした。ネットワーク接続、またはCORS設定" +
                "(main.pyのallow_origins)を確認し、ページを再読み込みしてください。"
            );
        }
    } else {
        adminScreen?.classList.add('hidden');
        pendingScreen?.classList.add('hidden');
        if (loginScreen) loginScreen.style.display = 'flex';
        ui.start('#firebaseui-auth-container', uiConfig);
    }
});

export async function logout() {
    await firebase.auth().signOut();
    showToast("ログアウトしました");
    setTimeout(() => location.reload(), 1000);
}

// 【Phase5.5】evaluator/backend起動直後はFirestoreからのデータ復元待ちで
// /api/*が503(Retry-After付き)を返す(main.py::_firestore_restore_gate参照)。
// これを通信エラーとして即座にユーザーへ見せるのではなく、ここで透過的に
// リトライすることで、画面上は「読み込みが数秒長い」だけの体験にする。
const AUTH_FETCH_MAX_RETRIES = 3;
const AUTH_FETCH_DEFAULT_RETRY_AFTER_SEC = 4; // Retry-Afterヘッダーが無い場合の既定待機秒数(3〜5秒の中間)。

function _sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function authFetch(url, options = {}, _retryCount = 0) {
    const user = firebase.auth().currentUser;
    if (!user) throw new Error("ログインしていません");
    const token = await user.getIdToken();
    const headers = { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` };
    const res = await fetch(url, { ...options, headers });

    if (res.status === 503) {
        if (_retryCount < AUTH_FETCH_MAX_RETRIES) {
            const retryAfterHeader = res.headers.get('Retry-After');
            const retryAfterSec = retryAfterHeader ? parseFloat(retryAfterHeader) : NaN;
            const waitSec = Number.isFinite(retryAfterSec) && retryAfterSec > 0
                ? retryAfterSec
                : AUTH_FETCH_DEFAULT_RETRY_AFTER_SEC;
            await _sleep(waitSec * 1000);
            return authFetch(url, options, _retryCount + 1);
        }
        // リトライ上限に達した場合のみ、ここで初めてエラーとしてユーザーへ見せる。
        let detail = "サーバーの起動処理(データ復元)が長引いています。しばらくしてから再読み込みしてください。";
        try {
            const body = await res.json();
            detail = body.message || body.detail || detail;
        } catch (e) {
            // レスポンスボディがJSONでない場合は既定文言のまま。
        }
        throw new Error(detail);
    }

    if (!res.ok) {
        if (res.status === 401) { logout(); throw new Error("認証切れ"); }
        // バックエンド(HTTPException)の detail をできる限り拾う
        // (persona_router/frontend/api.jsのfetchAPIと同じフォールバック規約)。
        let detail = `APIエラー: ${res.status}`;
        try {
            const body = await res.json();
            detail = body.detail || body.message || detail;
        } catch (e) {
            // レスポンスボディがJSONでない場合はHTTPステータスのみで諦める。
        }
        throw new Error(detail);
    }
    return res.json();
}

// モデル別の評価アクション。
// バックエンド(admin.py apply_human_action)は POST /admin/action + {target_slug, model, action}
// を受け付け、{"status": "success", "data": {...更新後のアイテム...}} を返す(エンベロープ化済み)。
// 旧承認待ちリスト描画パイプライン(091でパージ済み)が生成していたDOM要素
// (pendcol-*/pendstatus-*/pend-*/resolved-container)やwindow._adminPendingキャッシュへの
// 参照、および描画専用ヘルパー(_pendStatusBadge)は、描画元が既に存在せず到達不能な
// デッドコード(checkAndRefill()呼び出しは削除済み関数への浮いた参照でもあった)だったため、
// あわせて削除した(094)。実際に機能する部分(API呼び出しと結果トースト)のみを残す。
export async function modelAction(docId, model, action) {
    const labels = { golden: '殿堂入り', approve: '承認', reject: '棄却', delete: '削除' };
    try {
        /** @type {import('../api').components['schemas']['HumanActionRequest']} */
        const body = { target_slug: docId, model, action };
        await authFetch(`${API_BASE}/admin/action`, {
            method: 'POST',
            body: JSON.stringify(body)
        });
        showToast(`${model === 'gemini' ? 'Gemini' : 'ELYZA'}を${labels[action] || action}しました`);
        // 承認待ちパネル(pending-container)から対象アイテムを消すため一覧を再取得する。
        // DLQ操作(retryDlqItem/discardDlqItem)が成功後にloadDlqItems()するのと同じ規約。
        await loadPendingItems();
    } catch (e) { showToast("操作に失敗しました", "warning"); }
}

// DLQ(デッドレター/ポイズンピル隔離)管理。
// バックエンド(admin.py get_dlq_items/apply_dlq_action)は GET /admin/dlq で
// sync_status=="fatal" の一覧({items: [...]})を、POST /admin/dlq/action で
// {doc_id, action: 'retry'|'discard'} を受け付け {status, doc_id, action} を返す。
/**
 * @returns {Promise<import('../api').components['schemas']['DlqListResponse']>}
 */
async function fetchDlqItems() {
    return authFetch(`${API_BASE}/admin/dlq`);
}

/**
 * @param {import('../api').components['schemas']['DlqItem']} item
 * @returns {string}
 */
function renderDlqItem(item) {
    const errText = (item.last_sync_error || '(不明なエラー)').replace(/</g, '&lt;');
    return `
        <div class="bg-red-50/40 border border-red-200 rounded-lg p-4">
            <div class="flex justify-between items-start gap-4">
                <div class="min-w-0">
                    <p class="font-bold text-gray-800 truncate">${item.odai || item.doc_id}${_newBadgeHtml(item.updated_at)}</p>
                    <p class="text-xs text-gray-500 mt-1">doc_id: ${item.doc_id} / retry_count: ${item.retry_count}</p>
                    <p class="text-xs text-red-700 mt-2 whitespace-pre-wrap break-all">${errText}</p>
                </div>
                <div class="flex flex-col gap-2 shrink-0">
                    <button data-action="retryDlqItem" data-doc-id="${item.doc_id}" class="text-xs bg-emerald-50 text-emerald-700 px-3 py-1 rounded hover:bg-emerald-100 transition border border-emerald-200">♻️ 再試行</button>
                    <button data-action="discardDlqItem" data-doc-id="${item.doc_id}" class="text-xs bg-gray-100 text-gray-600 px-3 py-1 rounded hover:bg-gray-200 transition border border-gray-200">🗑️ 破棄</button>
                </div>
            </div>
        </div>`;
}

async function loadDlqItems() {
    const container = document.getElementById('dlq-container');
    if (!container) return;
    try {
        const res = await fetchDlqItems();
        const items = res.items || [];
        container.innerHTML = items.length
            ? items.map(renderDlqItem).join('')
            : '<div class="text-center py-10 text-gray-400 text-sm">隔離中のアイテムはありません</div>';
    } catch (e) {
        container.innerHTML = '<div class="text-center py-10 text-red-500 text-sm">読み込みに失敗しました</div>';
        showToast("DLQ一覧の取得に失敗しました", "warning");
    }
}

export async function retryDlqItem(docId) {
    try {
        /** @type {import('../api').components['schemas']['DlqActionRequest']} */
        const body = { doc_id: docId, action: 'retry' };
        await authFetch(`${API_BASE}/admin/dlq/action`, { method: 'POST', body: JSON.stringify(body) });
        showToast("再試行キューへ戻しました");
        await loadDlqItems();
    } catch (e) { showToast("再試行に失敗しました", "warning"); }
}

export async function discardDlqItem(docId) {
    try {
        /** @type {import('../api').components['schemas']['DlqActionRequest']} */
        const body = { doc_id: docId, action: 'discard' };
        await authFetch(`${API_BASE}/admin/dlq/action`, { method: 'POST', body: JSON.stringify(body) });
        showToast("破棄しました");
        await loadDlqItems();
    } catch (e) { showToast("破棄に失敗しました", "warning"); }
}

// ------------------------------------------------------------
// 【Phase2新設】Ⅱレビュー: 直談判(unlock_requests)。
// バックエンド(admin_review.py)は apps/persona_router が所有する
// unlock_requests/user_penalties コレクションを直接読み書きする
// (共有Firestoreプロジェクト経由、cross-serviceのHTTP呼び出しは無い)。
// ------------------------------------------------------------

/**
 * @param {import('../api').components['schemas']['UnlockRequestListResponse']} [void]
 */
async function fetchUnlockRequests() {
    return authFetch(`${API_BASE}/admin/unlock-requests`);
}

function renderUnlockRequestItem(item) {
    const odai = item.offending_odai ? _escapeHtml(item.offending_odai) : '(記録なし)';
    const text = item.offending_text
        ? _escapeHtml(item.offending_text)
        : '※ このユーザーの直近のルートB(異常入力)生成物が見つかりませんでした';
    const message = _escapeHtml(item.message || '');
    const createdAt = item.created_at ? _formatMlopsTimestamp(item.created_at) : '';
    return `
        <div id="unlock-req-${_escapeHtml(item.request_id)}" class="bg-pink-50/30 border border-pink-200 rounded-lg p-4">
            <div class="flex justify-between items-start gap-2 mb-3">
                <p class="text-xs text-gray-400">client_uuid: ${_escapeHtml(item.client_uuid)}${createdAt ? ` / ${createdAt}` : ''}${_newBadgeHtml(item.created_at)}</p>
            </div>

            <div class="bg-white/70 border border-gray-200 rounded p-3 mb-2">
                <p class="text-[11px] font-bold text-red-700 mb-1">🔎 犯行現場(お題「${odai}」への回答)</p>
                <p class="text-sm text-gray-800 whitespace-pre-wrap break-all">${text}</p>
            </div>

            <div class="bg-white/70 border border-gray-200 rounded p-3 mb-3">
                <p class="text-[11px] font-bold text-blue-700 mb-1">🗣️ 本人の言い訳</p>
                <p class="text-sm text-gray-800 whitespace-pre-wrap break-all">${message}</p>
            </div>

            <div class="flex flex-wrap gap-2">
                <button data-action="handleUnlockAction" data-request-id="${_escapeHtml(item.request_id)}" data-unlock-action="pardon"
                    class="text-xs font-bold bg-emerald-50 text-emerald-700 px-3 py-1.5 rounded hover:bg-emerald-100 transition border border-emerald-200">
                    🙏 赦す(ブロック解除のみ)
                </button>
                <button data-action="handleUnlockAction" data-request-id="${_escapeHtml(item.request_id)}" data-unlock-action="reset"
                    class="text-xs font-bold bg-amber-50 text-amber-700 px-3 py-1.5 rounded hover:bg-amber-100 transition border border-amber-200">
                    🔄 リセット(カウントも0に)
                </button>
                <button data-action="handleUnlockAction" data-request-id="${_escapeHtml(item.request_id)}" data-unlock-action="reject"
                    class="text-xs font-bold bg-gray-100 text-gray-600 px-3 py-1.5 rounded hover:bg-gray-200 transition border border-gray-200">
                    🚫 却下
                </button>
            </div>
        </div>`;
}

async function loadUnlockRequests() {
    const container = document.getElementById('unlock-requests-container');
    if (!container) return;
    try {
        const res = await fetchUnlockRequests();
        const items = res.items || [];
        // 【Phase3】バックエンドがFirestoreクエリ失敗(複合インデックス未作成等)を
        // 空配列+warningへ縮退させて返すことがある(admin_review.py参照)。
        // 「未処理の直談判はありません」という誤解を招く空表示にせず、実際に
        // 何が起きたかをそのまま出す。
        if (res.warning) {
            container.innerHTML = `<div class="text-center py-10 text-amber-700 bg-amber-50 border border-amber-200 rounded-lg text-sm p-4 whitespace-pre-wrap">⚠️ ${_escapeHtml(res.warning)}</div>`;
            showToast('直談判一覧の取得中に警告が発生しました(詳細はⅡペイン参照)', 'warning');
            return;
        }
        container.innerHTML = items.length
            ? items.map(renderUnlockRequestItem).join('')
            : '<div class="text-center py-10 text-gray-400 text-sm">未処理の直談判はありません</div>';
    } catch (e) {
        container.innerHTML = '<div class="text-center py-10 text-red-500 text-sm">読み込みに失敗しました</div>';
        showToast("直談判一覧の取得に失敗しました", "warning");
    }
}

const UNLOCK_ACTION_LABELS = { pardon: '赦し', reset: 'リセット', reject: '却下' };

export async function handleUnlockAction(requestId, action) {
    if (action === 'reset' && !window.confirm('ペナルティ回数ごと完全にリセットします。よろしいですか?')) return;
    try {
        await authFetch(`${API_BASE}/admin/unlock-requests/${encodeURIComponent(requestId)}/action`, {
            method: 'POST',
            body: JSON.stringify({ action }),
        });
        showToast(`${UNLOCK_ACTION_LABELS[action] || action}しました`);
        await loadUnlockRequests();
        await loadActionRequiredSummary();
    } catch (e) {
        showToast(`操作に失敗しました: ${e.message}`, 'warning');
    }
}

// ------------------------------------------------------------
// 【Phase5/6】5段階評価(review_status)。承認待ちデータ・RLHFレビューの両カードから
// 共通で呼ぶ(旧「⭐ Few-shot採用」ボタンを廃止し置き換え)。
// ①🏆Golden を選んだ場合のみ、Phase2の13評価軸タグの選択を必須とし、確定時に
// POST .../review(review_status)とPOST .../fewshot(is_fewshot_selected+タグ)を
// 続けて呼ぶ(バックエンド側もreview_status=="golden"でない限りfewshot採用を
// 拒否する対称的なガードを持つ、apps/evaluator/backend/api/routers/admin_review.py
// ::update_fewshot_selection参照)。
// ------------------------------------------------------------

const REVIEW_STATUS_OPTIONS = [
    { value: 'golden', emoji: '🏆', label: 'Golden' },
    { value: 'good', emoji: '🟢', label: 'Good' },
    { value: 'hmm', emoji: '⚪', label: 'Hmm' },
    { value: 'tolerable', emoji: '🟡', label: 'Tolerable' },
    { value: 'troll', emoji: '🔴', label: 'Troll' },
];

// 承認待ちデータ・RLHFレビューの両カードから共通で埋め込む5段階評価UIブロック。
// ボタン選択→(Golden時のみ)タグ選択→確定ボタン、の3段階(main_admin.jsの
// CLICK_ACTIONS経由でselectReviewStatus/confirmReviewStatusへディスパッチされる)。
function _renderReviewActionHtml(docId) {
    const buttonsHtml = REVIEW_STATUS_OPTIONS.map((opt) => `
        <button data-action="selectReviewStatus" data-doc-id="${docId}" data-review-status="${opt.value}"
            class="review-status-btn text-xs font-bold bg-white text-gray-700 px-2.5 py-1.5 rounded border border-gray-300 hover:bg-gray-50 transition">
            ${opt.emoji} ${opt.label}
        </button>`).join('');
    const axisOptionsHtml = Object.entries(AXIS_LABELS)
        .map(([code, label]) => `<option value="${code}">${code}(${label})</option>`)
        .join('');
    return `
        <div class="mt-3 pt-3 border-t border-gray-100">
            <p class="text-xs font-bold text-gray-500 mb-2">📋 5段階評価</p>
            <div class="flex flex-wrap gap-1.5 mb-2" id="review-buttons-${docId}">${buttonsHtml}</div>
            <div id="axis-select-wrap-${docId}" class="hidden mb-2">
                <select id="axis-select-${docId}" class="text-xs border border-gray-300 rounded px-2 py-1.5 w-full">
                    <option value="">-- ①🏆Golden採用時: Few-shot評価軸タグを選択(必須) --</option>
                    ${axisOptionsHtml}
                </select>
            </div>
            <button data-action="confirmReviewStatus" data-doc-id="${docId}" id="review-confirm-${docId}" disabled
                class="text-xs font-bold bg-gray-200 text-gray-400 px-3 py-1.5 rounded cursor-not-allowed transition w-full">
                評価を確定
            </button>
        </div>`;
}

export function selectReviewStatus(docId, status) {
    const buttonsWrap = document.getElementById(`review-buttons-${docId}`);
    if (buttonsWrap) {
        buttonsWrap.querySelectorAll('button').forEach((btn) => {
            const selected = /** @type {HTMLElement} */ (btn).dataset.reviewStatus === status;
            btn.classList.toggle('ring-2', selected);
            btn.classList.toggle('ring-[#902A19]', selected);
            btn.classList.toggle('bg-[#FAF8F5]', selected);
        });
    }
    const axisWrap = document.getElementById(`axis-select-wrap-${docId}`);
    if (axisWrap) axisWrap.classList.toggle('hidden', status !== 'golden');

    const confirmBtn = /** @type {HTMLButtonElement | null} */ (document.getElementById(`review-confirm-${docId}`));
    if (confirmBtn) {
        confirmBtn.dataset.selectedStatus = status;
        confirmBtn.disabled = false;
        confirmBtn.classList.remove('bg-gray-200', 'text-gray-400', 'cursor-not-allowed');
        confirmBtn.classList.add('bg-[#2C3539]', 'text-white', 'hover:bg-gray-800');
    }
}

// 評価済みカードをフェードアウトさせてDOMから取り除く(承認待ち・RLHFレビュー
// 両パネルに同じdoc_idのカードが同時に存在し得るため、両方のid規約を試す)。
function _fadeOutAndRemoveCard(docId) {
    [`pending-card-${docId}`, `feedback-card-${docId}`].forEach((cardId) => {
        const card = document.getElementById(cardId);
        if (!card) return;
        card.style.transition = 'opacity 0.3s, transform 0.3s';
        card.style.opacity = '0';
        card.style.transform = 'scale(0.96) translateY(-10px)';
        setTimeout(() => card.remove(), 300);
    });
}

export async function confirmReviewStatus(docId) {
    const confirmBtn = /** @type {HTMLButtonElement | null} */ (document.getElementById(`review-confirm-${docId}`));
    const status = confirmBtn?.dataset.selectedStatus;
    if (!status) {
        showToast('5段階評価を選択してください', 'warning');
        return;
    }

    let axisTag = '';
    if (status === 'golden') {
        const select = /** @type {HTMLSelectElement | null} */ (document.getElementById(`axis-select-${docId}`));
        axisTag = select ? select.value : '';
        if (!axisTag) {
            showToast('①🏆Goldenの場合はFew-shot評価軸タグの選択が必須です', 'warning');
            return;
        }
    }

    try {
        await authFetch(`${API_BASE}/admin/nazokake-items/${encodeURIComponent(docId)}/review`, {
            method: 'POST',
            body: JSON.stringify({ review_status: status }),
        });
    } catch (e) {
        showToast(`評価の確定に失敗しました: ${e.message}`, 'warning');
        return;
    }

    if (status === 'golden') {
        try {
            await authFetch(`${API_BASE}/admin/nazokake-items/${encodeURIComponent(docId)}/fewshot`, {
                method: 'POST',
                body: JSON.stringify({ is_fewshot_selected: true, fewshot_axis_tag: axisTag }),
            });
        } catch (e) {
            // review_status自体は既に確定済みのため、Few-shot採用の失敗はカードを
            // 消さずに警告のみに留める(admin.pyの承認待ちキューからは既に外れているが、
            // 未採用のまま気づかず放置されないよう管理者へ明示する)。
            showToast(`5段階評価(Golden)は保存されましたが、Few-shot採用に失敗しました: ${e.message}`, 'warning');
        }
    }

    showToast('✅ 評価完了');
    _fadeOutAndRemoveCard(docId);
    loadActionRequiredSummary();
}

// MLOps推移ダッシュボード(CQRSに基づく静的JSONダンプ方式)。
// メインAPI(apps/evaluator/backend)を一切経由せず、/api/admin/metrics相当の
// エンドポイントにも依存しない。tools/mlops_pipeline_nazo.py / tools/mlops_pipeline_agent.py
// がパイプライン完了時にtools/export_metrics.py経由でアトミックに書き出す
// apps/evaluator/frontend/public/data/metrics.json を直接fetchするだけの、
// 常に読み取り専用の静的ダンプ(認証・バックエンド起動状態に依存しない)。
let _mlopsChart = null;

// tools/export_metrics.pyのDashboardMetricsSchema.schema_versionと対応するバージョン。
// 【絶対制約】fetchしたJSONのschema_versionがこれと一致しない場合、パース・描画を
// 直ちに中止し、textContentのみでエラーメッセージを表示する(Graceful Degradation、
// innerHTML等によるXSSの経路を構造的に排除する)。
const MLOPS_METRICS_SCHEMA_VERSION = '1.0';

/**
 * @param {string} timestamp ISO8601文字列
 * @returns {string} "YYYY-MM-DD HH:MM:SS"形式(グラフの横軸ラベル用)
 */
function _formatMlopsTimestamp(timestamp) {
    return (timestamp || '').replace('T', ' ').slice(0, 19);
}

/**
 * @param {string} message
 */
function showMlopsChartError(message) {
    const canvas = document.getElementById('mlops-chart');
    const emptyEl = document.getElementById('mlops-chart-empty');
    const errorEl = document.getElementById('mlops-chart-error');
    if (canvas) canvas.classList.add('hidden');
    if (emptyEl) emptyEl.classList.add('hidden');
    if (errorEl) {
        errorEl.textContent = message;
        errorEl.classList.remove('hidden');
    }
}

/**
 * @param {Array<Record<string, any>>} rows
 */
function renderMlopsChart(rows) {
    const canvas = /** @type {HTMLCanvasElement | null} */ (document.getElementById('mlops-chart'));
    const emptyEl = document.getElementById('mlops-chart-empty');
    const errorEl = document.getElementById('mlops-chart-error');
    if (!canvas) return;
    if (errorEl) errorEl.classList.add('hidden');

    if (!rows.length) {
        canvas.classList.add('hidden');
        if (emptyEl) emptyEl.classList.remove('hidden');
        return;
    }
    canvas.classList.remove('hidden');
    if (emptyEl) emptyEl.classList.add('hidden');

    const labels = rows.map((r) => `[${r.pipeline_type}] ${_formatMlopsTimestamp(r.timestamp)}`);
    const successRates = rows.map((r) => r.success_rate);
    const regressionRates = rows.map((r) => r.regression_rate);

    if (_mlopsChart) _mlopsChart.destroy();
    _mlopsChart = new Chart(canvas.getContext('2d'), {
        type: 'line',
        data: {
            labels,
            datasets: [
                {
                    label: 'Success Rate',
                    data: successRates,
                    borderColor: 'rgba(91, 129, 36, 1)',
                    backgroundColor: 'rgba(91, 129, 36, 0.1)',
                    tension: 0.2,
                    spanGaps: true,
                },
                {
                    label: 'Regression Rate',
                    data: regressionRates,
                    borderColor: 'rgba(197, 88, 88, 1)',
                    backgroundColor: 'rgba(197, 88, 88, 0.1)',
                    tension: 0.2,
                    spanGaps: true,
                },
            ],
        },
        options: {
            responsive: true,
            scales: { y: { min: 0, max: 1.0 } },
            plugins: { legend: { display: true } },
        },
    });
}

// mlops-schedulerデーモンの生存監視タイル(CQRSに基づく静的JSONダンプ方式)。
// loadMlopsMetrics()と同様、バックエンドAPIには一切依存しない。tools/scheduler_daemon.py
// がサイクルごとにtools/export_daemon_heartbeat.py経由でアトミックに書き出す
// apps/evaluator/frontend/public/data/daemon_heartbeat.json を直接fetchするだけの、
// 常に読み取り専用の静的ダンプ(instructions/169)。
// tools/export_daemon_heartbeat.pyのDaemonHeartbeatSchema.schema_versionと対応する
// バージョン。
const DAEMON_HEARTBEAT_SCHEMA_VERSION = '1.0';

// 【SRE差し戻し対応: 陳腐化(Staleness)判定】tools/scheduler_daemon.pyのサイクル
// 間隔(INTERVAL_SEC = 3600秒 = 1時間)に対し、実行1回分の処理時間+ネットワーク的な
// 揺らぎを吸収する5分のグレース期間を加えた閾値。generated_at(JSON自体が最後に
// 書き出された時刻)からこの閾値を超えて時間が経過している場合、JSON自身が
// 報告するstatus(仮に最後がstatus: "ok"だったとしても)を信用せず、必ず
// 「陳腐化(灰色・警告)」表示へ強制的に倒す。デーモンプロセス自体が死んでいる場合、
// JSONは最後の(古い)内容のまま static に残り続けるため、status単体の表示だけでは
// 「本当に稼働中」と「過去に稼働していた形跡が残っているだけ」を区別できない
// (このタイル自体が生存確認そのものなので、判定基準もタイムスタンプでなければ
// 意味を持たない)。
const DAEMON_HEARTBEAT_STALE_THRESHOLD_MS = (60 + 5) * 60 * 1000;

const DAEMON_HEARTBEAT_STATUS_STYLE = {
    ok: { dot: 'bg-green-500', label: '稼働中' },
    skipped: { dot: 'bg-yellow-400', label: '稼働中(閾値未達のためスキップ)' },
    error: { dot: 'bg-red-500', label: '異常終了' },
    unknown: { dot: 'bg-gray-400', label: '不明' },
    stale: { dot: 'bg-gray-400', label: '⚠️ 陳腐化(更新が停止している疑い)' },
};

/**
 * @param {{status?: string, message?: string, generated_at?: string, last_cycle_finished_at?: string}} data
 */
function renderDaemonHeartbeat(data) {
    const dot = document.getElementById('daemon-heartbeat-dot');
    const text = document.getElementById('daemon-heartbeat-text');
    if (!dot || !text) return;

    // generated_atが無い(fetch自体に失敗した等)場合は陳腐化判定の対象外とし、
    // 渡されたstatus(通常はunknown)をそのまま表示する。generated_atがあり、
    // かつ閾値を超えて古い場合にのみ、報告されたstatusを上書きして陳腐化扱いにする。
    const generatedAtMs = data?.generated_at ? new Date(data.generated_at).getTime() : NaN;
    const ageMs = Number.isNaN(generatedAtMs) ? null : Date.now() - generatedAtMs;
    const isStale = ageMs !== null && ageMs > DAEMON_HEARTBEAT_STALE_THRESHOLD_MS;

    const style = isStale
        ? DAEMON_HEARTBEAT_STATUS_STYLE.stale
        : (DAEMON_HEARTBEAT_STATUS_STYLE[data?.status] || DAEMON_HEARTBEAT_STATUS_STYLE.unknown);
    dot.className = `inline-block w-3 h-3 rounded-full flex-shrink-0 ${style.dot}`;

    // 【絶対制約】textContentのみを用いる(innerHTML等によるXSSの経路を構造的に
    // 排除する。showMlopsChartError()と同じ流儀)。
    const lastPolled = data?.last_cycle_finished_at
        ? _formatMlopsTimestamp(data.last_cycle_finished_at)
        : '(未取得)';
    const parts = [style.label, `最終ポーリング: ${lastPolled}`];
    if (data?.message) parts.push(data.message);
    if (isStale) parts.push(`(最終更新から${Math.round(ageMs / 60000)}分経過。デーモン停止の疑いあり)`);
    text.textContent = parts.join(' / ');
}

async function loadDaemonHeartbeat() {
    try {
        const res = await fetch('/data/daemon_heartbeat.json');
        if (!res.ok) throw new Error(`静的JSON取得エラー: ${res.status}`);
        const data = await res.json();

        // 【絶対制約】schema_versionを最初に検証する。対応バージョンでなければ、
        // このJSONの構造を信用してパース・描画することは一切せず、直ちに中止して
        // 縮退運転(Graceful Degradation)する。
        if (data.schema_version !== DAEMON_HEARTBEAT_SCHEMA_VERSION) {
            console.warn(
                `⚠️ デーモン生存監視のschema_versionが未対応です(受信: ${data.schema_version}, ` +
                `対応: ${DAEMON_HEARTBEAT_SCHEMA_VERSION})。描画を中止します。`
            );
            renderDaemonHeartbeat({ status: 'unknown', message: 'システムの更新が必要です' });
            return;
        }

        renderDaemonHeartbeat(data);
    } catch (e) {
        console.warn('⚠️ デーモン生存監視の取得に失敗しました(サイドカー未起動の場合は正常):', e);
        renderDaemonHeartbeat({ status: 'unknown', message: '(サイドカー未起動、または未実行)' });
    }
}

async function loadMlopsMetrics() {
    try {
        const res = await fetch('/data/metrics.json');
        if (!res.ok) throw new Error(`静的JSON取得エラー: ${res.status}`);
        const data = await res.json();

        // 【絶対制約】schema_versionを最初に検証する。対応バージョンでなければ、
        // このJSONの構造を信用してパース・描画することは一切せず、直ちに中止して
        // 縮退運転(Graceful Degradation)する。
        if (data.schema_version !== MLOPS_METRICS_SCHEMA_VERSION) {
            console.warn(
                `⚠️ MLOpsメトリクスのschema_versionが未対応です(受信: ${data.schema_version}, ` +
                `対応: ${MLOPS_METRICS_SCHEMA_VERSION})。描画を中止します。`
            );
            showMlopsChartError('システムの更新が必要です');
            return;
        }

        renderMlopsChart(data.rows || []);
    } catch (e) {
        console.warn('⚠️ MLOps推移メトリクスの取得に失敗しました(未実行の場合は正常):', e);
        renderMlopsChart([]);
    }
}

// 監査証跡(Audit Logs)ビュー。バックエンド(admin.py get_audit_logs)は
// GET /admin/audit_logs で audit_logsテーブルをcreated_at降順・最大100件で返す
// ({items: [...]})。DLQのretry/discardはdatabase.py側で監査ログ追記と同一
// トランザクションになっているため、この一覧はそれらの操作の不変な追記専用証跡。
/**
 * @returns {Promise<import('../api').components['schemas']['AuditLogListResponse']>}
 */
async function fetchAuditLogs() {
    return authFetch(`${API_BASE}/admin/audit_logs`);
}

// 【絶対制約】innerHTML/insertAdjacentHTMLは使用しない。要素はすべて
// document.createElement()で生成し、データはelement.textContentでのみ注入する。
/**
 * @param {import('../api').components['schemas']['AuditLogItem']} item
 * @returns {HTMLTableRowElement}
 */
function renderAuditLogRow(item) {
    const tr = document.createElement('tr');
    tr.className = 'border-b border-gray-100';

    const cells = [
        item.created_at || '',
        item.actor || '',
        item.action || '',
        item.target_item_id || '',
        item.reason ? JSON.stringify(item.reason) : '',
    ];
    for (const value of cells) {
        const td = document.createElement('td');
        td.className = 'py-2 pr-4 align-top break-all';
        td.textContent = value;
        tr.appendChild(td);
    }
    return tr;
}

async function loadAuditLogs() {
    const container = document.getElementById('audit-log-container');
    if (!container) return;
    while (container.firstChild) container.removeChild(container.firstChild);
    try {
        const res = await fetchAuditLogs();
        const items = res.items || [];
        if (!items.length) {
            const tr = document.createElement('tr');
            const td = document.createElement('td');
            td.colSpan = 5;
            td.className = 'text-center py-10 text-gray-400 text-sm';
            td.textContent = '監査証跡はありません';
            tr.appendChild(td);
            container.appendChild(tr);
            return;
        }
        for (const item of items) {
            container.appendChild(renderAuditLogRow(item));
        }
    } catch (e) {
        while (container.firstChild) container.removeChild(container.firstChild);
        const tr = document.createElement('tr');
        const td = document.createElement('td');
        td.colSpan = 5;
        td.className = 'text-center py-10 text-red-500 text-sm';
        td.textContent = '読み込みに失敗しました';
        tr.appendChild(td);
        container.appendChild(tr);
        showToast("監査証跡の取得に失敗しました", "warning");
    }
}

// RLHFレビュー(モデル別 人間評価＋コメント)。
// バックエンド(admin_feedbacks.py get_admin_feedbacks)は GET /admin/feedbacks で
// user_feedbacks コレクションを created_at 降順で返す(配列を直接返す。
// {items: [...]}のようなラップは無い点がDLQ/監査証跡と異なる)。
/**
 * @returns {Promise<Array<{doc_id: string, user_uid: string, overall_score: number, comment: string, model_target: 'gemini'|'elyza', created_at: string}>>}
 */
async function fetchModelFeedbacks() {
    return authFetch(`${API_BASE}/admin/feedbacks`);
}

/**
 * @param {{doc_id?: string, overall_score?: number, comment?: string, model_target?: string, created_at?: string}} item
 * @returns {string}
 */
function renderModelFeedbackItem(item) {
    const isGemini = item.model_target === 'gemini';
    const modelLabel = isGemini ? 'Gemini' : 'ELYZA';
    const modelBadgeClass = isGemini
        ? 'bg-blue-50 text-blue-700 border-blue-200'
        : 'bg-emerald-50 text-emerald-700 border-emerald-200';
    const score = item.overall_score != null ? `★${item.overall_score}/5` : '(評価なし)';
    const comment = (item.comment || '(コメントなし)').replace(/</g, '&lt;');
    const createdAt = item.created_at ? _formatMlopsTimestamp(item.created_at) : '';
    return `
        <div class="bg-gray-50 border border-gray-200 rounded-lg p-4" ${item.doc_id ? `id="feedback-card-${item.doc_id}"` : ''}>
            <div class="flex justify-between items-start gap-4">
                <div class="min-w-0 flex-1">
                    <div class="flex items-center gap-2 mb-1">
                        <span class="text-xs font-bold px-2 py-0.5 rounded border ${modelBadgeClass}">${modelLabel}</span>
                        <span class="text-xs font-bold text-[#C5B358]">${score}</span>
                    </div>
                    <p class="text-xs text-gray-500">doc_id: ${item.doc_id || '(不明)'}</p>
                    <p class="text-sm text-gray-800 mt-2 whitespace-pre-wrap break-all">${comment}</p>
                    ${item.doc_id ? _renderReviewActionHtml(item.doc_id) : ''}
                </div>
                <p class="text-xs text-gray-400 shrink-0">${createdAt}</p>
            </div>
        </div>`;
}

async function loadModelFeedback() {
    const container = document.getElementById('model-feedback-container');
    if (!container) return;
    try {
        const items = await fetchModelFeedbacks();
        container.innerHTML = Array.isArray(items) && items.length
            ? items.map(renderModelFeedbackItem).join('')
            : '<div class="text-center py-10 text-gray-400 text-sm">フィードバックはまだありません</div>';
    } catch (e) {
        container.innerHTML = '<div class="text-center py-10 text-red-500 text-sm">読み込みに失敗しました</div>';
        showToast("RLHFレビューの取得に失敗しました", "warning");
    }
}

// 【instructions/172: 1-Click Deploy】POST /api/admin/deploy がtools/deploy/
// run_verification_server.ps1をバックグラウンドで起動する。ボタン押下後、
// deploy.log(バックエンドが標準出力/標準エラー出力を追記するプレーンテキスト)を
// 定期的にfetchし、差分のみをターミナル風<textarea>へ追記する(SSH接続・ターミナル
// 操作を一切必要としない)。
const DEPLOY_LOG_POLL_INTERVAL_MS = 3000;
let _deployLogPollTimer = null;
let _deployLogLastLength = 0;

/**
 * @param {string} text
 */
function _appendDeployLogText(text) {
    const terminal = /** @type {HTMLTextAreaElement | null} */ (
        document.getElementById('deploy-log-terminal')
    );
    if (!terminal) return;
    // 【絶対制約】textContentのみを用いる(innerHTML等によるXSSの経路を構造的に
    // 排除する)。<textarea>自体はvalueで内容を保持するため、末尾への追記は
    // value += で行う(textContentへの代入は<textarea>の表示内容には反映されない)。
    terminal.value += text;
    terminal.scrollTop = terminal.scrollHeight;
}

async function pollDeployLog() {
    try {
        // キャッシュを回避するためタイムスタンプ付きクエリでfetchする。
        const res = await fetch(`/data/deploy.log?_=${Date.now()}`);
        if (!res.ok) return; // デプロイ未実行(ログ未生成)の404は正常系として無視する。
        const text = await res.text();
        if (text.length > _deployLogLastLength) {
            _appendDeployLogText(text.slice(_deployLogLastLength));
            _deployLogLastLength = text.length;
        }
    } catch (e) {
        console.warn('⚠️ デプロイログの取得に失敗しました:', e);
    }
}

function startDeployLogPolling() {
    if (_deployLogPollTimer) return;
    _deployLogPollTimer = setInterval(pollDeployLog, DEPLOY_LOG_POLL_INTERVAL_MS);
    pollDeployLog();
}

export async function deployToProduction() {
    const btn = /** @type {HTMLButtonElement | null} */ (
        document.getElementById('deploy-btn')
    );
    if (btn) btn.disabled = true;
    try {
        const result = await authFetch(`${API_BASE}/admin/deploy`, { method: 'POST' });
        showToast(result.message || "デプロイを開始しました");
        startDeployLogPolling();
    } catch (e) {
        showToast("デプロイの開始に失敗しました", "warning");
    } finally {
        if (btn) btn.disabled = false;
    }
}

// アプリ利用状況(テレメトリ)。バックエンド(metrics.py get_metrics_summary)は
// GET /metrics/summary で、直近_SUMMARY_SAMPLE_LIMIT件のtelemetry_logsから
// インメモリ集計したPV/UU/平均滞在時間/イベント別件数を返す({pv, uu,
// avg_duration_sec, events: [{event_name, count}], sampled_events, note})。
// 全期間の厳密な値ではなく直近サンプルからの近似値のため、noteをそのまま表示する。
/**
 * @param {HTMLElement} container
 * @param {Array<{event_name: string, count: number}>} events
 */
function _renderAppUsageEvents(container, events) {
    while (container.firstChild) container.removeChild(container.firstChild);
    if (!events.length) {
        const p = document.createElement('p');
        p.className = 'text-gray-400 text-center py-2';
        p.textContent = 'イベントはまだありません';
        container.appendChild(p);
        return;
    }
    for (const ev of events) {
        const row = document.createElement('div');
        row.className = 'flex justify-between items-center border-b border-gray-100 pb-1.5';
        const nameSpan = document.createElement('span');
        nameSpan.className = 'text-gray-600';
        // 【絶対制約】event_nameはPOST /metrics/logへ未認証で送信可能なため
        // (app.js等からのテレメトリ計測は匿名ユーザーからも呼ばれる)、信頼できない
        // 入力として扱いtextContentのみで注入する(innerHTML等によるXSSの経路を
        // 構造的に排除する)。
        nameSpan.textContent = ev.event_name;
        const countSpan = document.createElement('span');
        countSpan.className = 'font-bold text-gray-800';
        countSpan.textContent = String(ev.count);
        row.appendChild(nameSpan);
        row.appendChild(countSpan);
        container.appendChild(row);
    }
}

async function loadAppUsage() {
    const pvEl = document.getElementById('adm-pv');
    const uuEl = document.getElementById('adm-uu');
    const durEl = document.getElementById('adm-dur');
    const eventsContainer = document.getElementById('adm-events-container');
    try {
        const data = await authFetch(`${API_BASE}/metrics/summary`);
        if (pvEl) pvEl.textContent = String(data.pv ?? 0);
        if (uuEl) uuEl.textContent = String(data.uu ?? 0);
        if (durEl) {
            while (durEl.firstChild) durEl.removeChild(durEl.firstChild);
            durEl.appendChild(document.createTextNode(String(Math.round(data.avg_duration_sec || 0))));
            const unit = document.createElement('span');
            unit.className = 'text-xs font-normal text-gray-500';
            unit.textContent = '秒';
            durEl.appendChild(unit);
        }
        if (eventsContainer) {
            _renderAppUsageEvents(eventsContainer, data.events || []);
            if (data.note) {
                const note = document.createElement('p');
                note.className = 'text-[10px] text-gray-400 text-right pt-1';
                note.textContent = data.note;
                eventsContainer.appendChild(note);
            }
        }
    } catch (e) {
        if (pvEl) pvEl.textContent = '—';
        if (uuEl) uuEl.textContent = '—';
        if (durEl) durEl.textContent = '—';
        if (eventsContainer) eventsContainer.innerHTML = '<p class="text-red-500 text-center py-2 text-sm">データ取得失敗</p>';
        showToast("アプリ利用状況の取得に失敗しました", "warning");
    }
}

// 承認待ちデータ。バックエンド(nazokake_core.database::async_get_pending_items)は
// GET /admin/pending で「review_status IS NULL」かつ(道場破りの赤ペン/自作投稿は
// 無条件、AI生成は道場破りでのユーザー評価が1件以上ある行のみ)を作成日時降順で
// 最大50件返す({items: [...]}、Phase5/6でフィードバックループ統合)。
// 各アイテムの"pending"状態のモデル側にのみ承認/棄却ボタンを描画する
// (_renderPendingActionButtons、gemini/elyzaどちらの生成結果を採用するかの旧来の
// キュレーションであり、5段階評価(review_status)とは独立した別軸)。クリックは
// main_admin.jsのCLICK_ACTIONS経由でmodelAction(docId, model, action)へ
// ディスパッチされ、成功後はこのパネルの再取得(loadPendingItems())まで行う
// (modelAction内部で完結)。
/**
 * @returns {Promise<{items: Array<Record<string, any>>}>}
 */
async function fetchPendingItems() {
    return authFetch(`${API_BASE}/admin/pending`);
}

/**
 * @param {Record<string, any>} item
 * @returns {string}
 */
/**
 * @param {string} docId
 * @param {'gemini'|'elyza'} model
 * @returns {string}
 */
function _renderPendingActionButtons(docId, model) {
    return `
        <div class="flex gap-2 mt-2">
            <button data-action="modelAction" data-doc-id="${docId}" data-model="${model}" data-model-action="approve"
                class="text-xs bg-emerald-50 text-emerald-700 px-3 py-1 rounded hover:bg-emerald-100 transition border border-emerald-200">✅ 承認</button>
            <button data-action="modelAction" data-doc-id="${docId}" data-model="${model}" data-model-action="reject"
                class="text-xs bg-red-50 text-red-600 px-3 py-1 rounded hover:bg-red-100 transition border border-red-200">🚫 棄却</button>
        </div>`;
}

// 【Phase5/6】道場破り経由のユーザー評価(human_evaluations、最新3件まで)を
// カード内に要約表示する。5段階評価の判断材料として直接関わるため表示する。
function _renderHumanEvaluationsHtml(evaluations) {
    if (!Array.isArray(evaluations) || evaluations.length === 0) return '';
    const rows = evaluations.slice(-3).map((ev) => {
        const score = ev && ev.user_score != null ? `★${ev.user_score}` : '';
        const comment = _escapeHtml((ev && ev.comment) || '');
        const slug = _escapeHtml((ev && ev.user_slug) || 'anonymous');
        return `<p class="text-xs text-gray-600">${score} <span class="text-gray-400">(${slug})</span> ${comment}</p>`;
    }).join('');
    return `<div class="mt-2 bg-gray-50 border border-gray-100 rounded p-2 space-y-1">${rows}</div>`;
}

function renderPendingItem(item) {
    const odai = (item.odai || '').replace(/</g, '&lt;');
    const geminiText = (item.nazokake_text || '(未生成)').replace(/</g, '&lt;');
    const elyzaText = (item.nazokake_text_llmjp || '(未生成)').replace(/</g, '&lt;');
    const gScore = item.s_total != null ? ` / ${item.s_total}点` : '';
    const eScore = item.s_total_llmjp != null ? ` / ${item.s_total_llmjp}点` : '';
    const createdAt = item.created_at ? _formatMlopsTimestamp(item.created_at) : '';
    return `
        <div class="bg-white border border-gray-200 rounded-lg p-4 shadow-sm" id="pending-card-${item.doc_id}">
            <p class="font-bold text-gray-800">${odai}${_originTypeBadgeHtml(item.origin_type)}${_newBadgeHtml(item.created_at)}</p>
            <p class="text-xs text-gray-400 mt-1">doc_id: ${item.doc_id}${createdAt ? ` / ${createdAt}` : ''}</p>
            ${_renderHumanEvaluationsHtml(item.human_evaluations)}
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-3">
                <div class="bg-blue-50/40 border border-blue-100 rounded p-3">
                    <p class="text-xs font-bold text-blue-700 mb-1">Gemini (${item.gemini_status || 'n/a'}${gScore})</p>
                    <p class="text-sm text-gray-700 whitespace-pre-wrap break-all">${geminiText}</p>
                    ${item.gemini_status === 'pending' ? _renderPendingActionButtons(item.doc_id, 'gemini') : ''}
                </div>
                <div class="bg-emerald-50/40 border border-emerald-100 rounded p-3">
                    <p class="text-xs font-bold text-emerald-700 mb-1">ELYZA (${item.elyza_status || 'n/a'}${eScore})</p>
                    <p class="text-sm text-gray-700 whitespace-pre-wrap break-all">${elyzaText}</p>
                    ${item.elyza_status === 'pending' ? _renderPendingActionButtons(item.doc_id, 'elyza') : ''}
                </div>
            </div>
            ${_renderReviewActionHtml(item.doc_id)}
        </div>`;
}

async function loadPendingItems() {
    const container = document.getElementById('pending-container');
    if (!container) return;
    try {
        const res = await fetchPendingItems();
        const items = res.items || [];
        container.innerHTML = items.length
            ? items.map(renderPendingItem).join('')
            : '<div class="text-center py-10 text-gray-400 text-sm">承認待ちのデータはありません</div>';
    } catch (e) {
        container.innerHTML = '<div class="text-center py-10 text-red-500 text-sm">データ取得失敗</div>';
        showToast("承認待ちデータの取得に失敗しました", "warning");
    }
}

// ------------------------------------------------------------
// 【Phase 0新設】Ⅴ運用基盤: 招待発行・承認待ち管理者一覧(admin_auth.py)。
// ------------------------------------------------------------

function _escapeHtml(s) {
    return String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// 招待メール送信フォーム(data-action="submitInvite"、main_admin.js経由で呼ばれる)。
export async function submitInvite() {
    const input = /** @type {HTMLInputElement | null} */ (document.getElementById('invite-email-input'));
    const email = (input?.value || '').trim();
    if (!email) {
        showToast('招待するメールアドレスを入力してください', 'warning');
        return;
    }
    const btn = /** @type {HTMLButtonElement | null} */ (document.getElementById('invite-submit-btn'));
    if (btn) btn.disabled = true;
    try {
        const res = await authFetch(`${API_BASE}/admin/invites`, {
            method: 'POST',
            body: JSON.stringify({ email }),
        });
        showToast(res.message || '招待メールを送信しました');
        if (input) input.value = '';
    } catch (e) {
        showToast(`招待の発行に失敗しました: ${e.message}`, 'warning');
    } finally {
        if (btn) btn.disabled = false;
    }
}

function _renderPendingAdminItem(item) {
    return `
        <div class="flex justify-between items-center bg-indigo-50/40 border border-indigo-100 rounded-lg p-3">
            <div class="min-w-0">
                <p class="font-bold text-gray-800 text-sm truncate">${_escapeHtml(item.email)}${_newBadgeHtml(item.requested_at)}</p>
                <p class="text-xs text-gray-400">uid: ${_escapeHtml(item.uid)}${item.requested_at ? ` / 申請日時: ${_escapeHtml(item.requested_at)}` : ''}</p>
            </div>
            <button data-action="approveAdminUser" data-uid="${_escapeHtml(item.uid)}"
                class="shrink-0 text-xs font-bold bg-emerald-50 text-emerald-700 px-3 py-1.5 rounded hover:bg-emerald-100 transition border border-emerald-200">
                ✅ 承認
            </button>
        </div>`;
}

async function loadPendingAdminUsers() {
    const container = document.getElementById('pending-admins-container');
    if (!container) return;
    try {
        const res = await authFetch(`${API_BASE}/admin/pending-admins`);
        const items = res.items || [];
        container.innerHTML = items.length
            ? items.map(_renderPendingAdminItem).join('')
            : '<div class="text-center py-6 text-gray-400 text-sm">承認待ちの管理者はいません</div>';
    } catch (e) {
        // オーナー以外がこのペインを開いた場合は403になる想定内のケースなので、
        // エラートーストは出さずメッセージ表示のみに留める。
        container.innerHTML = `<div class="text-center py-6 text-gray-400 text-sm">${_escapeHtml(e.message)}</div>`;
    }
}

export async function approveAdminUser(uid) {
    try {
        await authFetch(`${API_BASE}/admin/users/${encodeURIComponent(uid)}/approve`, { method: 'POST' });
        showToast('承認しました');
        await loadPendingAdminUsers();
    } catch (e) {
        showToast(`承認に失敗しました: ${e.message}`, 'warning');
    }
}

// ------------------------------------------------------------
// 【Phase3新設】Ⅲコストペイン: ①API/LLMトークンコスト。
// GET /admin/costs(system_costs自己ログ、最大100件)をservice_type別に
// 集計してテーブル+棒グラフで表示する。/admin/costs/dashboard(サーバー
// レンダリング版)はBearerトークンをAuthorizationヘッダで送れない素朴な
// window.open()とは両立しない(Phase1でverify_admin_tokenを付与したため)
// ので、埋め込み表示(fetchベース)へ全面的に置き換えた。
// ------------------------------------------------------------

let _apiCostsChart = null;

function _aggregateApiCostsByService(costs) {
    const byService = new Map();
    for (const c of costs) {
        const key = c.service_type || '(不明)';
        const bucket = byService.get(key) || {
            service_type: key, count: 0, failed: 0,
            input_tokens: 0, output_tokens: 0, cost_jpy: 0,
        };
        bucket.count += 1;
        if (c.success === false) bucket.failed += 1;
        bucket.input_tokens += c.input_tokens || 0;
        bucket.output_tokens += c.output_tokens || 0;
        bucket.cost_jpy += c.calculated_cost_jpy || 0;
        byService.set(key, bucket);
    }
    return [...byService.values()].sort((a, b) => b.cost_jpy - a.cost_jpy);
}

function _renderApiCostsTable(rows) {
    const tbody = document.getElementById('api-costs-table-body');
    if (!tbody) return;
    if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="text-center py-10 text-gray-400 text-sm">コストログはまだありません</td></tr>';
        return;
    }
    tbody.innerHTML = rows.map((r) => `
        <tr class="border-b border-gray-100">
            <td class="py-2 pr-4 font-bold">${_escapeHtml(r.service_type)}</td>
            <td class="py-2 pr-4">${r.count}</td>
            <td class="py-2 pr-4 ${r.failed ? 'text-red-600 font-bold' : ''}">${r.failed}</td>
            <td class="py-2 pr-4">${r.input_tokens.toLocaleString()}</td>
            <td class="py-2 pr-4">${r.output_tokens.toLocaleString()}</td>
            <td class="py-2 pr-4 font-bold">¥${r.cost_jpy.toFixed(2)}</td>
        </tr>`).join('');
}

function _renderApiCostsChart(rows) {
    const canvas = /** @type {HTMLCanvasElement | null} */ (document.getElementById('api-costs-chart'));
    if (!canvas) return;
    if (_apiCostsChart) _apiCostsChart.destroy();
    if (!rows.length) return;
    _apiCostsChart = new Chart(canvas.getContext('2d'), {
        type: 'bar',
        data: {
            labels: rows.map((r) => r.service_type),
            datasets: [{
                label: 'コスト(円)',
                data: rows.map((r) => r.cost_jpy),
                backgroundColor: 'rgba(37, 99, 235, 0.5)',
                borderColor: 'rgba(37, 99, 235, 1)',
                borderWidth: 1,
            }],
        },
        options: { responsive: true, plugins: { legend: { display: false } } },
    });
}

async function loadApiCosts() {
    const totalEl = document.getElementById('api-costs-total');
    const budgetEl = document.getElementById('api-costs-budget');
    try {
        const costs = await authFetch(`${API_BASE}/admin/costs`);
        const rows = _aggregateApiCostsByService(costs);
        const totalJpy = rows.reduce((sum, r) => sum + r.cost_jpy, 0);
        if (totalEl) totalEl.textContent = `¥${totalJpy.toFixed(2)}`;
        // 予算消化率はサーバーレンダリング版(costs_dashboard.html)と同じ
        // MONTHLY_BUDGET_JPYを前提にした概算をここでは省略し、合計金額のみを
        // 一次情報として表示する(予算上限値はサーバー側の環境変数でしか
        // 分からないため、フロントで二重管理・値のズレを起こさないための判断)。
        if (budgetEl) budgetEl.textContent = costs.length ? `${costs.length}件` : '0件';
        _renderApiCostsTable(rows);
        _renderApiCostsChart(rows);
    } catch (e) {
        if (totalEl) totalEl.textContent = '—';
        if (budgetEl) budgetEl.textContent = '—';
        const tbody = document.getElementById('api-costs-table-body');
        if (tbody) tbody.innerHTML = '<tr><td colspan="6" class="text-center py-10 text-red-500 text-sm">読み込みに失敗しました</td></tr>';
        showToast('APIコストの取得に失敗しました', 'warning');
    }
}

// ------------------------------------------------------------
// 【Phase3新設】Ⅲコストペイン: ②GCPインフラコスト。
// GET /admin/gcp-costs(system_gcp_costs/latestの薄いラッパー)を表示するだけ。
// BigQueryへは一切触れない(集計はサーバー側の日次バッチ
// POST /admin/jobs/sync-gcp-costsが別途行う)。
// ------------------------------------------------------------

async function loadGcpCosts() {
    const dateEl = document.getElementById('gcp-costs-date');
    const totalEl = document.getElementById('gcp-costs-total');
    const tbody = document.getElementById('gcp-costs-table-body');
    const emptyNote = document.getElementById('gcp-costs-empty-note');
    const generatedAtEl = document.getElementById('gcp-costs-generated-at');
    try {
        const res = await authFetch(`${API_BASE}/admin/gcp-costs`);
        const hasData = !!res.date;
        emptyNote?.classList.toggle('hidden', hasData);

        if (dateEl) dateEl.textContent = res.date || '(未実行)';
        if (totalEl) totalEl.textContent = hasData ? `${(res.currency || '')} ${res.total_cost.toFixed(2)}`.trim() : '-';
        if (generatedAtEl) generatedAtEl.textContent = res.generated_at ? `最終集計: ${_formatMlopsTimestamp(res.generated_at)}` : '';

        const breakdown = res.breakdown || [];
        if (tbody) {
            tbody.innerHTML = breakdown.length
                ? breakdown.map((b) => `
                    <tr class="border-b border-gray-100">
                        <td class="py-2 pr-4">${_escapeHtml(b.service_description)}</td>
                        <td class="py-2 pr-4 font-bold">${(res.currency || '')} ${b.cost.toFixed(2)}</td>
                    </tr>`).join('')
                : '<tr><td colspan="2" class="text-center py-10 text-gray-400 text-sm">内訳データはありません</td></tr>';
        }
    } catch (e) {
        if (dateEl) dateEl.textContent = '—';
        if (totalEl) totalEl.textContent = '—';
        if (tbody) tbody.innerHTML = '<tr><td colspan="2" class="text-center py-10 text-red-500 text-sm">読み込みに失敗しました</td></tr>';
        showToast('GCPインフラコストの取得に失敗しました', 'warning');
    }
}

// ------------------------------------------------------------
// 【Phase1新設】お知らせバッジ(action-required-summary)。
// ------------------------------------------------------------

function _updateBadge(elId, count) {
    const el = document.getElementById(elId);
    if (!el) return;
    if (!count) {
        el.classList.add('hidden');
        el.textContent = '';
        return;
    }
    el.textContent = String(count);
    el.classList.remove('hidden');
}

async function loadActionRequiredSummary() {
    try {
        const res = await authFetch(`${API_BASE}/admin/action-required-summary`);
        // 以降のload*()(DLQ/承認待ちデータ/承認待ち管理者)が🆕判定に使う基準時刻。
        // initAdmin()側でこの関数を他のload*()より先にawaitすることで、
        // レンダリング時には必ず確定済みの状態にしている。
        _previousLoginAt = res.previous_login_at || null;

        _updateBadge('global-action-badge', res.total);
        // Ⅰ: DLQ。Ⅱ: レビュー(承認待ちデータ)+直談判(準備中、現時点ではunlock分を合算)。
        // Ⅴ: 承認待ち管理者。
        _updateBadge('tab-badge-1', res.dlq.total);
        _updateBadge('tab-badge-2', res.review.total + res.unlock.total);
        _updateBadge('tab-badge-5', res.admin_approval.total);

        // 【Phase3】Firestore側カウント(直談判/承認待ち管理者)の一部がインデックス
        // 未作成等で0件へ縮退した場合、バッジの数字を鵜呑みにさせないよう警告する
        // (admin_health.py::get_action_required_summary参照)。
        if (res.warning) {
            console.warn('⚠️ お知らせバッジの一部集計に失敗しました:', res.warning);
            showToast('一部のお知らせ件数が正しく取得できていません(詳細はコンソール参照)', 'warning');
        }
    } catch (e) {
        // お知らせバッジはあくまで付加情報であり、取得失敗が画面全体を止める
        // 理由にはならない(既存のload*()群と同じグレースフルデグラデーション方針)。
        console.warn('⚠️ お知らせバッジの取得に失敗しました:', e);
    }
}

// ------------------------------------------------------------
// 【Phase1新設】APIエラー率
// ------------------------------------------------------------

function _renderApiErrorRateByService(byService) {
    const container = document.getElementById('api-error-rate-by-service');
    if (!container) return;
    if (!byService || !byService.length) {
        container.textContent = '';
        return;
    }
    container.innerHTML = byService
        .map((s) => `<div>${s.service_type}: ${(s.error_rate * 100).toFixed(1)}% (${s.failed}/${s.total}件)</div>`)
        .join('');
}

async function loadApiErrorRate() {
    const valueEl = document.getElementById('api-error-rate-value');
    const failedEl = document.getElementById('api-error-rate-failed');
    const totalEl = document.getElementById('api-error-rate-total');
    try {
        const res = await authFetch(`${API_BASE}/admin/api-error-rate`);
        if (valueEl) valueEl.textContent = `${(res.error_rate * 100).toFixed(1)}%`;
        if (failedEl) failedEl.textContent = String(res.failed);
        if (totalEl) totalEl.textContent = String(res.total);
        _renderApiErrorRateByService(res.by_service);
    } catch (e) {
        if (valueEl) valueEl.textContent = '—';
        if (failedEl) failedEl.textContent = '—';
        if (totalEl) totalEl.textContent = '—';
        console.warn('⚠️ APIエラー率の取得に失敗しました:', e);
    }
}

// ------------------------------------------------------------
// 【persona_feature_plan_v3.md Phase8新設】3層(構造/反応/訂正)データセット基盤の集計
// ------------------------------------------------------------

async function loadDatasetLayerSummary() {
    const structureEl = document.getElementById('dataset-layer-structure-total');
    const reactionEl = document.getElementById('dataset-layer-reaction-total');
    const correctionEl = document.getElementById('dataset-layer-correction-total');
    const warningEl = document.getElementById('dataset-layer-summary-warning');
    try {
        const res = await authFetch(`${API_BASE}/admin/dataset-layer-summary`);
        if (structureEl) structureEl.textContent = String(res.structure.total);
        if (reactionEl) reactionEl.textContent = String(res.reaction.total);
        if (correctionEl) correctionEl.textContent = String(res.correction.total);
        if (warningEl) {
            if (res.warning) {
                warningEl.textContent = `⚠️ ${res.warning}`;
                warningEl.classList.remove('hidden');
            } else {
                warningEl.classList.add('hidden');
            }
        }
    } catch (e) {
        if (structureEl) structureEl.textContent = '—';
        if (reactionEl) reactionEl.textContent = '—';
        if (correctionEl) correctionEl.textContent = '—';
        console.warn('⚠️ 3層データセット集計の取得に失敗しました:', e);
    }
}

// ------------------------------------------------------------
// 【Phase4新設】Ⅳ生成設定: ペルソナ管理(3段階ライフサイクル)。
// ------------------------------------------------------------

const PERSONA_MODE_LABELS = {
    default: { text: 'デフォルト', badge: 'bg-gray-100 text-gray-500 border-gray-200' },
    permanent: { text: '永続上書き中', badge: 'bg-indigo-100 text-indigo-700 border-indigo-300' },
    temporary: { text: '時限上書き中', badge: 'bg-amber-100 text-amber-700 border-amber-300' },
};

// 直談判ブロック画面(apps/persona_router/frontend/app.js::formatRemaining)と
// 同じ考え方の残り時間フォーマッタ(このファイル内で完結させる、共有モジュール化は
// 別サービスをまたぐため見送る)。
function _formatPersonaRemaining(expiresAtIso) {
    const diffMs = new Date(expiresAtIso).getTime() - Date.now();
    if (diffMs <= 0) return 'まもなく失効';
    const totalMinutes = Math.ceil(diffMs / 60000);
    const hours = Math.floor(totalMinutes / 60);
    const minutes = totalMinutes % 60;
    if (hours > 0) return `残り${hours}時間${minutes}分`;
    return `残り${minutes}分`;
}

function _personaStatusBadgeHtml(item) {
    const info = PERSONA_MODE_LABELS[item.mode] || PERSONA_MODE_LABELS.default;
    const suffix = item.mode === 'temporary' && item.expires_at
        ? `(${_formatPersonaRemaining(item.expires_at)})`
        : '';
    return `<span class="inline-block text-[11px] font-bold px-2 py-0.5 rounded-full border ${info.badge}">${info.text}${suffix}</span>`;
}

function renderPersonaConfigItem(item) {
    const promptPreview = item.prompt.length > 80 ? `${item.prompt.slice(0, 80)}…` : item.prompt;
    return `
        <div class="border border-gray-200 rounded-lg p-4" id="persona-row-${item.persona_id}">
            <div class="flex justify-between items-start gap-3 mb-2">
                <div class="min-w-0">
                    <p class="font-bold text-gray-800">#${item.persona_id} ${_escapeHtml(item.name)}</p>
                    <div class="mt-1">${_personaStatusBadgeHtml(item)}</div>
                </div>
                <div class="flex gap-2 shrink-0">
                    <button data-action="openPersonaEditModal" data-persona-id="${item.persona_id}"
                        class="text-xs font-bold bg-gray-100 hover:bg-gray-200 text-gray-700 px-3 py-1.5 rounded transition border border-gray-200">
                        ✏️ 編集
                    </button>
                    <button data-action="clearPersonaConfig" data-persona-id="${item.persona_id}"
                        ${item.mode === 'default' ? 'disabled' : ''}
                        class="text-xs font-bold px-3 py-1.5 rounded transition border ${item.mode === 'default' ? 'bg-gray-50 text-gray-300 border-gray-100 cursor-not-allowed' : 'bg-red-50 hover:bg-red-100 text-red-600 border-red-200'}">
                        🧹 クリア
                    </button>
                </div>
            </div>
            <p class="text-xs text-gray-500 whitespace-pre-wrap">${_escapeHtml(promptPreview)}</p>
        </div>`;
}

// 編集モーダルを開く際、最新のプロンプト本文を参照できるようメモリに保持しておく
// (一覧はプレビュー(80文字)しか表示しないため)。
let _personaConfigsCache = [];

async function loadPersonaConfigs() {
    const container = document.getElementById('personas-container');
    if (!container) return;
    try {
        const res = await authFetch(`${API_BASE}/admin/personas`);
        _personaConfigsCache = res.personas || [];
        container.innerHTML = _personaConfigsCache.length
            ? _personaConfigsCache.map(renderPersonaConfigItem).join('')
            : '<div class="text-center py-10 text-gray-400 text-sm">ペルソナが見つかりません</div>';
    } catch (e) {
        container.innerHTML = '<div class="text-center py-10 text-red-500 text-sm">読み込みに失敗しました</div>';
        showToast('ペルソナ一覧の取得に失敗しました', 'warning');
    }
}

export function openPersonaEditModal(personaId) {
    const item = _personaConfigsCache.find((p) => p.persona_id === Number(personaId));
    if (!item) return;

    document.getElementById('persona-edit-id').value = item.persona_id;
    document.getElementById('persona-edit-title').textContent = `#${item.persona_id} ${item.name} を編集`;
    document.getElementById('persona-edit-name').value = item.name;
    document.getElementById('persona-edit-prompt').value = item.prompt;

    // 現在時限適用中なら「24時間」を初期選択にしておく等の細かい親切機能は持たず、
    // 常に「① 登録(24時間)」を既定選択にする(誤操作で恒久適用してしまう事故を
    // 防ぐ、保守的なデフォルト)。
    const radios = document.querySelectorAll('input[name="persona-edit-duration"]');
    radios.forEach((r) => { r.checked = r.value === '24h'; });

    document.getElementById('persona-edit-modal')?.classList.remove('hidden');
}

export function closePersonaEditModal() {
    document.getElementById('persona-edit-modal')?.classList.add('hidden');
}

export async function savePersonaConfig() {
    const personaId = document.getElementById('persona-edit-id').value;
    const name = document.getElementById('persona-edit-name').value.trim();
    const prompt = document.getElementById('persona-edit-prompt').value.trim();
    const durationPreset = document.querySelector('input[name="persona-edit-duration"]:checked')?.value || '24h';

    if (!prompt) {
        showToast('プロンプトを入力してください', 'warning');
        return;
    }

    const saveBtn = document.getElementById('persona-edit-save');
    if (saveBtn) saveBtn.disabled = true;
    try {
        await authFetch(`${API_BASE}/admin/personas/${encodeURIComponent(personaId)}`, {
            method: 'PUT',
            body: JSON.stringify({ name: name || null, prompt, duration_preset: durationPreset }),
        });
        showToast('ペルソナ設定を保存しました');
        closePersonaEditModal();
        await loadPersonaConfigs();
    } catch (e) {
        showToast(`保存に失敗しました: ${e.message}`, 'warning');
    } finally {
        if (saveBtn) saveBtn.disabled = false;
    }
}

export async function clearPersonaConfig(personaId) {
    if (!window.confirm('上書き設定をクリアし、初期値へ戻します。よろしいですか?')) return;
    try {
        await authFetch(`${API_BASE}/admin/personas/${encodeURIComponent(personaId)}`, {
            method: 'DELETE',
        });
        showToast('初期値へ戻しました');
        await loadPersonaConfigs();
    } catch (e) {
        showToast(`クリアに失敗しました: ${e.message}`, 'warning');
    }
}

// 管理画面初期化フック。091のDDD再編でパージされた「アプリ利用状況」
// 「承認待ちデータ」は、対応するバックエンドAPI(/api/metrics/summary,
// /api/admin/pending)をmain.py/metrics.py/admin.pyへ新設した上で読込を再実装した。
async function initAdmin() {
    document.getElementById('dlq-reload-btn')?.addEventListener('click', () => loadDlqItems());
    document.getElementById('audit-log-reload-btn')?.addEventListener('click', () => loadAuditLogs());
    document.getElementById('model-feedback-reload-btn')?.addEventListener('click', () => loadModelFeedback());
    document.getElementById('app-usage-reload-btn')?.addEventListener('click', () => loadAppUsage());
    document.getElementById('pending-reload-btn')?.addEventListener('click', () => loadPendingItems());
    document.getElementById('pending-admins-reload-btn')?.addEventListener('click', () => loadPendingAdminUsers());
    document.getElementById('unlock-requests-reload-btn')?.addEventListener('click', () => loadUnlockRequests());
    document.getElementById('api-costs-reload-btn')?.addEventListener('click', () => loadApiCosts());
    document.getElementById('gcp-costs-reload-btn')?.addEventListener('click', () => loadGcpCosts());
    document.getElementById('personas-reload-btn')?.addEventListener('click', () => loadPersonaConfigs());
    document.getElementById('persona-edit-close')?.addEventListener('click', () => closePersonaEditModal());

    // 【重要】バッジ集計(_previousLoginAtの確定)を他のload*()より先に完了させる。
    // これより後のload*()群(DLQ/承認待ちデータ/承認待ち管理者)は_previousLoginAtを
    // 参照して🆕バッジを描画するため、並列実行(Promise.allSettled)に混ぜてしまうと
    // レースコンディションで🆕が付いたり付かなかったりする不安定な挙動になる。
    await loadActionRequiredSummary();

    // 各読込は独立した非同期処理のため Promise.allSettled で実行する。
    // load*()内部は個別にtry/catchしフォールバック表示するため通常rejectしないが、
    // 想定外の例外が発生した場合でも他セクションの描画を妨げないための二重の
    // 安全策として allSettled を用いる(直列await + 未catch例外だと、そこで
    // 後続の読込ごと止まってしまうため)。
    await Promise.allSettled([
        loadDlqItems(),
        loadDaemonHeartbeat(),
        loadMlopsMetrics(),
        loadAuditLogs(),
        loadModelFeedback(),
        loadAppUsage(),
        loadPendingItems(),
        loadPendingAdminUsers(),
        loadApiErrorRate(),
        loadDatasetLayerSummary(),
        loadUnlockRequests(),
        loadApiCosts(),
        loadGcpCosts(),
        loadPersonaConfigs(),
    ]);
}
