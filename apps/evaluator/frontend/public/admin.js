import { firebaseConfig } from "firebase-config";

const API_BASE = (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') ? 'http://127.0.0.1:7800/api' : 'https://nazokake-backend-r6jq2erkta-an.a.run.app/api';

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

// 🔐 Firebase Auth 状態の監視
firebase.auth().onAuthStateChanged((user) => {
    const loginScreen = document.getElementById('login-screen');
    const adminScreen = document.getElementById('admin-screen');
    if (user) {
        if(loginScreen) loginScreen.style.display = 'none';
        if(adminScreen) adminScreen.classList.remove('hidden');
        initAdmin();
    } else {
        if(loginScreen) loginScreen.style.display = 'flex';
        if(adminScreen) adminScreen.classList.add('hidden');
        ui.start('#firebaseui-auth-container', uiConfig);
    }
});

export async function logout() {
    await firebase.auth().signOut();
    showToast("ログアウトしました");
    setTimeout(() => location.reload(), 1000);
}

export async function authFetch(url, options = {}) {
    const user = firebase.auth().currentUser;
    if (!user) throw new Error("ログインしていません");
    const token = await user.getIdToken();
    const headers = { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` };
    const res = await fetch(url, { ...options, headers });
    if (!res.ok) {
        if (res.status === 401) { logout(); throw new Error("認証切れ"); }
        throw new Error(`APIエラー: ${res.status}`);
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
                    <p class="font-bold text-gray-800 truncate">${item.odai || item.doc_id}</p>
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
        <div class="bg-gray-50 border border-gray-200 rounded-lg p-4">
            <div class="flex justify-between items-start gap-4">
                <div class="min-w-0">
                    <div class="flex items-center gap-2 mb-1">
                        <span class="text-xs font-bold px-2 py-0.5 rounded border ${modelBadgeClass}">${modelLabel}</span>
                        <span class="text-xs font-bold text-[#C5B358]">${score}</span>
                    </div>
                    <p class="text-xs text-gray-500">doc_id: ${item.doc_id || '(不明)'}</p>
                    <p class="text-sm text-gray-800 mt-2 whitespace-pre-wrap break-all">${comment}</p>
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

// 「アプリ利用状況」「承認待ちデータ」は、対応するバックエンドAPI(旧
// /admin/pending, /admin/config, /admin/metrics)がDDD再編で091にてフロント
// ロジックごと一括パージされたまま再実装されていない(main.pyへ復旧・登録した
// 現行ルーター群(admin/admin_costs/admin_feedbacks/board/generate/metrics等)にも
// 「一覧を返す」同等のエンドポイントは存在しない)。データが無いままfetchを
// 試み続けて「読み込んでいます...」に恒久的に固まるよりは、未対応であることを
// 明示するフォールバック表示に倒す(バックエンド側でAPIが新設され次第、
// showUnavailable()の呼び出しをfetchベースのload関数へ置き換える)。
/**
 * @param {string} containerId
 * @param {string} label
 */
function showUnavailable(containerId, label) {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = `<div class="text-center py-10 text-gray-400 text-sm">⚠️ ${label}: 対応するバックエンドAPIが未実装のため表示できません</div>`;
}

// 管理画面初期化フック。RLHFレビュー(/admin/feedbacks)は main.py への復旧登録に
// 伴い読込を再実装した。「アプリ利用状況」「承認待ちデータ」は対応APIが
// 依然として存在しないため showUnavailable() でフォールバックする(上記コメント参照)。
async function initAdmin() {
    document.getElementById('dlq-reload-btn')?.addEventListener('click', () => loadDlqItems());
    document.getElementById('audit-log-reload-btn')?.addEventListener('click', () => loadAuditLogs());
    document.getElementById('model-feedback-reload-btn')?.addEventListener('click', () => loadModelFeedback());

    showUnavailable('adm-events-container', 'アプリ利用状況');
    showUnavailable('pending-container', '承認待ちデータ');

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
    ]);
}
