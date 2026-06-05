const API_BASE = (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') ? 'http://127.0.0.1:8000/api' : 'https://nazokake-backend-r6jq2erkta-an.a.run.app/api';
let adminUserId = '';
let adminPasscode = '';

function showToast(msg, type='info') {
    const c = document.getElementById('toast-container');
    const t = document.createElement('div');
    t.className = `toast ${type}`;
    t.innerText = msg;
    c.appendChild(t);
    setTimeout(() => { t.style.opacity = 0; setTimeout(() => t.remove(), 300); }, 3000);
}

async function loginAdmin() {
    adminUserId = document.getElementById('admin-user').value;
    adminPasscode = document.getElementById('admin-pass').value;
    if(!adminUserId || !adminPasscode) return showToast("⚠️ IDとパスワードを入力してください", "error");
    
    const success = await loadAdminFeed();
    if(success) {
        document.getElementById('login-section').classList.add('hidden');
        document.getElementById('dashboard-section').classList.remove('hidden');
        showToast("🔓 コックピットへようこそ");
        loadSettings();
    }
}

function logoutAdmin() {
    adminUserId = ''; adminPasscode = '';
    document.getElementById('admin-user').value = '';
    document.getElementById('admin-pass').value = '';
    document.getElementById('login-section').classList.remove('hidden');
    document.getElementById('dashboard-section').classList.add('hidden');
    document.getElementById('admin-list').innerHTML = '';
    showToast("🚪 ログアウトしました");
}

// 🎛️ AIエンジンの設定を保存
async function saveSettings() {
    const temp = parseFloat(document.getElementById('setting-temp').value);
    const model = document.getElementById('setting-model').value;
    const prompt = document.getElementById('setting-prompt').value;

    try {
        const res = await fetch(`${API_BASE}/admin/settings`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'x-admin-user': adminUserId,
                'x-admin-pass': adminPasscode
            },
            body: JSON.stringify({
                temperature: temp,
                model_name: model,
                system_prompt: prompt
            })
        });
        if (res.status === 401) return logoutAdmin();
        if (!res.ok) throw new Error("設定の保存に失敗しました");
        showToast("💾 AIエンジンの設定をシステムに反映しました！");
    } catch (e) {
        showToast(`エラー: ${e.message}`, 'error');
    }
}

// 🎛️ AIエンジンの設定を読み込み
async function loadSettings() {
    try {
        const res = await fetch(`${API_BASE}/admin/settings`, {
            headers: { 'x-admin-user': adminUserId, 'x-admin-pass': adminPasscode }
        });
        if (!res.ok) return;
        const data = await res.json();
        
        if (data.temperature) document.getElementById('setting-temp').value = data.temperature;
        if (data.model_name) document.getElementById('setting-model').value = data.model_name;
        if (data.system_prompt) document.getElementById('setting-prompt').value = data.system_prompt;
    } catch (e) {
        console.error("設定読み込みエラー", e);
    }
}

async function loadAdminFeed() {
    const container = document.getElementById('admin-list');
    container.innerHTML = '<p style="color: #888;">通信中...</p>';
    
    try {
        const res = await fetch(`${API_BASE}/admin/feed`, {
            headers: { 'x-admin-user': adminUserId, 'x-admin-pass': adminPasscode }
        });
        if (res.status === 401) {
            adminUserId = ''; adminPasscode = '';
            throw new Error("🔑 認証情報が違います");
        }
        if (!res.ok) throw new Error("データの取得に失敗しました");
        
        const data = await res.json();
        if (!data.items || data.items.length === 0) {
            container.innerHTML = '<p style="color: #aaa;">現在、承認待ちのデータはありません。ユーザーの評価を待ちましょう。</p>';
            return true;
        }
        renderAdminList(data.items);
        return true;
    } catch (e) {
        showToast(`エラー: ${e.message}`, "error");
        container.innerHTML = '<p style="color: #ff4500;">通信エラーが発生しました。</p>';
        return false;
    }
}

// ✍️ レンダリング (お題編集フィールドとIPブロックボタンを追加)
function renderAdminList(items) {
    const container = document.getElementById('admin-list');
    container.innerHTML = '';
    
    items.forEach(item => {
        const row = document.createElement('div');
        row.className = 'item-row';
        row.id = `admin-row-${item.id}`;
        
        const odai = item.odai || item.A_TITLE || "不明";
        const toku = item.result?.toku || "";
        const kokoro = item.result?.kokoro || "";
        const score = item.s_total || item.total_score || 0;
        const comment = item.human_comment || "コメントなし";
        const ipAddress = item.submitter_ip || "不明 (記録前データ)";
        
        row.innerHTML = `
            <div class="item-info">
                <div style="margin-bottom: 8px;">
                    <span style="color:var(--golden); font-size: 0.9rem; font-weight:bold;">【お題】</span><br>
                    <input type="text" id="edit-odai-${item.id}" value="${odai}" class="edit-input edit-odai">
                </div>
                
                <div style="margin-bottom: 5px;">
                    <span style="color:#aaa; font-size: 0.9rem;">解き:</span><br>
                    <input type="text" id="edit-toku-${item.id}" value="${toku}" class="edit-input">
                </div>
                <div>
                    <span style="color:#aaa; font-size: 0.9rem;">心:</span><br>
                    <textarea id="edit-kokoro-${item.id}" class="edit-input" rows="2">${kokoro}</textarea>
                </div>
                
                <div class="item-meta">
                    <span class="score-box">⭐ ユーザー評価: ${score}.0</span><br>
                    <div style="margin-top: 8px; padding-bottom: 8px; border-bottom: 1px dashed #444;">
                        <span style="color: #4CAF50; font-weight: bold;">💬 指導コメント:</span> 
                        <span style="color:#fff;">${comment}</span>
                    </div>
                    <div style="margin-top: 8px;">
                        送信元IP: <span class="ip-box">${ipAddress}</span>
                        ${(ipAddress && ipAddress !== "不明 (記録前データ)" && ipAddress !== "unknown") ? `<button class="btn-ban" onclick="banIpAddress('${ipAddress}')">🚨 このIPをブロック(荒らし対策)</button>` : ''}
                    </div>
                </div>
            </div>
            
            <div class="item-actions">
                <button class="btn-golden" style="background-color: var(--golden); color: black;" onclick="approveAdminItem('${item.id}', 3.0)">🏆 Tier A (殿堂/学習+RAG)</button>
                <button class="btn-golden" style="background-color: #C0C0C0; color: black; margin-top: 8px;" onclick="approveAdminItem('${item.id}', 2.0)">🥇 Tier B (優秀/学習のみ)</button>
                <button class="btn-golden" style="background-color: #CD7F32; color: black; margin-top: 8px;" onclick="approveAdminItem('${item.id}', 1.5)">🥈 Tier C (承認/学習除外)</button>
                <button class="btn-save" style="margin-top: 15px; width: 100%; border: 1px solid #aaa;" onclick="resetEvalItem('${item.id}')">🔄 評価のみリセット (白紙化)</button>
                <button class="btn-delete" style="margin-top: 8px; width: 100%;" onclick="deleteItem('${item.id}')">💣 完全抹殺 (DBから物理削除)</button>
            </div>
        `;
        container.appendChild(row);
    });
}

// 🚨 荒らしIPブロックロジック
async function banIpAddress(ip) {
    if(!confirm(`⚠️ 警告: IPアドレス [ ${ip} ] をブラックリストに登録しますか？
今後のこのIPからの送信はすべて遮断されます。`)) return;
    
    try {
        const res = await fetch(`${API_BASE}/admin/ban_ip`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'x-admin-user': adminUserId, 'x-admin-pass': adminPasscode },
            body: JSON.stringify({ ip_address: ip, reason: "コクピットからの手動ブロック" })
        });

        if (res.status === 401) return logoutAdmin();
        if (!res.ok) throw new Error("ブロック処理に失敗しました");

        showToast(`🚨 成功: IP [ ${ip} ] をシステムから遮断しました`, "error");
    } catch (e) { showToast(`エラー: ${e.message}`, "error"); }
}

async function approveAdminItem(docId, tier) {
    if(!confirm("このデータを本番のAI学習用手本として確定しますか？")) return;
    
    // 🌟 追加: お題の修正も取得
    const finalOdai = document.getElementById(`edit-odai-${docId}`).value;
    const finalToku = document.getElementById(`edit-toku-${docId}`).value;
    const finalKokoro = document.getElementById(`edit-kokoro-${docId}`).value;
    
    try {
        const res = await fetch(`${API_BASE}/admin/approve/${docId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'x-admin-user': adminUserId, 'x-admin-pass': adminPasscode },
            body: JSON.stringify({ 
                is_golden: tier === 3.0,
                tier: tier, 
                reviewer_id: "admin_takeshi",
                override_odai: finalOdai,
                override_toku: finalToku,
                override_kokoro: finalKokoro
            })
        });

        if (res.status === 401) return logoutAdmin();
        if (!res.ok) throw new Error("通信エラー");

        showToast("💮 ゴールデンデータとして承認・保存しました！");
        const row = document.getElementById(`admin-row-${docId}`);
        row.style.opacity = '0';
        setTimeout(() => row.remove(), 300);
    } catch (e) { showToast(`エラー: ${e.message}`, "error"); }
}

async function deleteItem(docId) {
    if(!confirm("⚠️ 本当にこのデータを破棄しますか？(復元不可)")) return;
    try {
        const res = await fetch(`${API_BASE}/admin/delete`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'x-admin-user': adminUserId, 'x-admin-pass': adminPasscode },
            body: JSON.stringify({ doc_id: docId })
        });

        if (res.status === 401) return logoutAdmin();
        if (!res.ok) throw new Error("通信エラー");

        showToast("🗑️ データを破棄しました。");
        const row = document.getElementById(`admin-row-${docId}`);
        row.style.opacity = '0';
        setTimeout(() => row.remove(), 300);
    } catch (e) { showToast(`エラー: ${e.message}`, "error"); }
}

async function resetEvalItem(docId) {
    if(!confirm("⚠️ このデータの「人間の評価」を白紙に戻し、再度タイムラインに流しますか？")) return;
    try {
        const res = await fetch(`${API_BASE}/admin/reset_eval/${docId}`, {
            method: 'POST',
            headers: { 'x-admin-user': adminUserId, 'x-admin-pass': adminPasscode }
        });
        if (res.status === 401) return logoutAdmin();
        if (!res.ok) throw new Error("通信エラー");

        showToast("🔄 評価をリセットし、再評価待ちに戻しました。");
        const row = document.getElementById(`admin-row-${docId}`);
        if(row) {
            row.style.opacity = '0';
            setTimeout(() => row.remove(), 300);
        }
    } catch (e) { showToast(`エラー: ${e.message}`, "error"); }
}
