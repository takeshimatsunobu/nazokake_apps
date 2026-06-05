const API_BASE = (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') ? 'http://127.0.0.1:8000/api' : 'https://nazokake-backend-r6jq2erkta-an.a.run.app/api';

function showToast(msg, type='info') {
    const container = document.getElementById('toast-container'); if(!container) return;
    const toast = document.createElement('div');
    toast.className = `bg-[#902A19] text-white px-6 py-3 rounded-full shadow-lg mb-2 text-sm font-bold transition-all duration-300 transform translate-y-0 opacity-100`;
    toast.innerText = msg;
    container.appendChild(toast);
    setTimeout(() => { toast.classList.add('opacity-0', '-translate-y-2'); setTimeout(() => toast.remove(), 300); }, 3000);
}

function checkAuth() {
    const token = localStorage.getItem('adminToken');
    if (!token) { showLoginModal(); return false; }
    return true;
}

function showLoginModal() {
    if(document.getElementById('login-modal')) return;
    const modal = document.createElement('div');
    modal.id = 'login-modal';
    modal.className = 'fixed inset-0 bg-gray-900 bg-opacity-95 flex items-center justify-center z-[1000]';
    modal.innerHTML = `
        <div class="bg-gray-800 p-8 rounded-xl shadow-2xl border border-gray-700 w-[400px]">
            <h2 class="text-white text-xl font-bold text-center mb-6 flex items-center justify-center gap-2"><span>🛡️</span> システム認証</h2>
            <input type="password" id="login-pass" placeholder="password (himitsu)" class="w-full mb-6 p-3 rounded bg-gray-100 text-gray-900 outline-none focus:ring-2 focus:ring-yellow-500">
            <button onclick="attemptLogin()" class="w-full bg-yellow-600 hover:bg-yellow-500 text-black font-bold py-3 rounded transition shadow-md">入室する</button>
        </div>
    `;
    document.body.appendChild(modal);
}

async function attemptLogin() {
    const p = document.getElementById('login-pass').value;
    try {
        const res = await fetch(`${API_BASE}/admin/login`, {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ password: p }) 
        });
        if (!res.ok) throw new Error("パスワードが違います");
        const data = await res.json();
        localStorage.setItem('adminToken', data.token);
        document.getElementById('login-modal').remove();
        showToast("認証に成功しました");
        initAdmin();
    } catch(e) { showToast("🚨 認証エラー: " + e.message, "warning"); }
}

function logout() {
    localStorage.removeItem('adminToken');
    location.reload();
}

async function fetchWithAuth(url, options = {}) {
    const token = localStorage.getItem('adminToken');
    const headers = { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` };
    const res = await fetch(url, { ...options, headers });
    if (res.status === 401) { logout(); throw new Error("認証切れ"); }
    if (!res.ok) throw new Error(`APIエラー: ${res.status}`);
    return res.json();
}

async function loadConfig() {
    try {
        const data = await fetchWithAuth(`${API_BASE}/admin/config`);
        document.getElementById('config-temp').value = data.temperature || 0.8;
        document.getElementById('temp-val-display').innerText = data.temperature || 0.8;
        document.getElementById('config-model').value = data.model_name || "gemini-1.5-flash";
        document.getElementById('config-prompt').value = data.system_prompt || "";
        document.getElementById('config-temp').addEventListener('input', (e) => document.getElementById('temp-val-display').innerText = e.target.value);
    } catch(e) { console.error("Config load error:", e); }
}

async function saveConfigs() {
    const t = parseFloat(document.getElementById('config-temp').value);
    const m = document.getElementById('config-model').value;
    const p = document.getElementById('config-prompt').value;
    try {
        await fetchWithAuth(`${API_BASE}/admin/config`, { method: 'POST', body: JSON.stringify({ temperature: t, model_name: m, system_prompt: p }) });
        showToast("設定を反映しました");
    } catch(e) { showToast("設定の保存に失敗しました", "warning"); }
}

async function loadPendingData() {
    const container = document.getElementById('pending-container');
    container.innerHTML = '<div class="text-center py-10 text-gray-500">読み込み中...</div>';
    try {
        const data = await fetchWithAuth(`${API_BASE}/admin/pending`);
        container.innerHTML = '';
        if(!data.items || data.items.length === 0) {
            container.innerHTML = '<div class="text-center py-10 text-gray-500">承認待ちのデータはありません</div>'; return;
        }
        data.items.forEach(item => {
            // 🚨 修正: 棄却(リセット)ボタンを追加
            container.insertAdjacentHTML('beforeend', `
                <div class="bg-gray-50 p-4 rounded border border-gray-200 shadow-sm" id="pend-${item.doc_id}">
                    <div class="mb-3"><span class="bg-green-100 text-green-800 text-xs font-bold px-2 py-1 rounded">⭐ ${item.total_score || item.s_total || '-'}</span></div>
                    <p class="font-bold text-sm text-[#902A19] mb-2">${item.A_TITLE || item.odai}</p>
                    <p class="text-sm text-gray-700 bg-white p-2 rounded border border-gray-100">${item.nazokake_text}</p>
                    <div class="flex gap-2 mt-4 flex-wrap">
                        <button onclick="approveItem('${item.doc_id}')" class="bg-blue-600 text-white px-4 py-1.5 rounded text-xs font-bold hover:bg-blue-700">✅ 承認(殿堂入り)</button>
                        <button onclick="resetItem('${item.doc_id}')" class="bg-gray-500 text-white px-4 py-1.5 rounded text-xs font-bold hover:bg-gray-600">🔄 棄却(道場に戻す)</button>
                        <button onclick="deleteItem('${item.doc_id}')" class="bg-red-600 text-white px-4 py-1.5 rounded text-xs font-bold hover:bg-red-700">🗑️ 削除(永久消去)</button>
                    </div>
                </div>
            `);
        });
    } catch(e) { 
        container.innerHTML = `<div class="text-red-500 text-center py-4">承認待ちデータの取得に失敗しました</div>`; 
        console.error("Pending data error:", e);
    }
}

async function approveItem(id) { try { await fetchWithAuth(`${API_BASE}/admin/approve/${id}`, {method:'POST'}); document.getElementById(`pend-${id}`).remove(); showToast("承認しました"); } catch(e) { showToast("承認失敗", "warning"); } }
async function deleteItem(id) { try { await fetchWithAuth(`${API_BASE}/admin/delete/${id}`, {method:'DELETE'}); document.getElementById(`pend-${id}`).remove(); showToast("削除しました"); } catch(e) { showToast("削除失敗", "warning"); } }

// 🚨 新規追加: リセット機能
async function resetItem(id) { 
    try { 
        await fetchWithAuth(`${API_BASE}/admin/reset/${id}`, {method:'POST'}); 
        document.getElementById(`pend-${id}`).remove(); 
        showToast("AIの初期状態にリセットし、道場に戻しました", "info"); 
    } catch(e) { 
        showToast("リセット失敗", "warning"); 
    } 
}

async function loadAdminMetrics() {
    try {
        const data = await fetchWithAuth(`${API_BASE}/admin/metrics`);
        document.getElementById('adm-pv').innerText = data.total_pvs || 0;
        document.getElementById('adm-uu').innerText = data.total_uus || 0;
        document.getElementById('adm-dur').innerText = `${data.avg_duration_sec || 0}秒`;
        const container = document.getElementById('adm-events-container'); container.innerHTML = '';
        const fNames = { 'page_view': '👥 初期訪問', 'tab_click': '🎛️ タブ切替', 'generate_requested': '🤖 生成リクエスト', 'human_submit': '🖌️ 自作鑑定依頼', 'evaluate_feed': '📤 道場破り送信', 'share_sns': '🔗 SNSシェア', 'page_leave': '🚪 ページ離脱 (セッション終了)' };
        for (let [key, val] of Object.entries(data.events || {})) {
            container.insertAdjacentHTML('beforeend', `<div class="flex justify-between py-2 border-b border-gray-200 border-dashed"><span class="text-gray-600 font-medium">${fNames[key]||key}</span><span class="font-bold text-gray-900 bg-gray-100 px-2 py-0.5 rounded text-xs">${val} 回</span></div>`);
        }
    } catch(e) { console.error("Metrics load error:", e); }
}

async function initAdmin() {
    if(!checkAuth()) return;
    loadConfig();
    loadPendingData();
    loadAdminMetrics();
}

window.onload = initAdmin;
