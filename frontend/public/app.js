let isUserFeedLoaded = false;
const API_BASE = (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') ? 'http://127.0.0.1:8000/api' : 'https://nazokake-backend-r6jq2erkta-an.a.run.app/api';
const APP_URL = "https://nazokakeapp-137e5.web.app/";

let myRadarChart = null; let humanRadarChart = null;
let userSlug = localStorage.getItem('nazokake_user_slug');
if (!userSlug) { userSlug = 'u_' + Math.random().toString(36).substring(2, 11); localStorage.setItem('nazokake_user_slug', userSlug); }
let sessionStartTime = Date.now();
let evaluatedItems = JSON.parse(localStorage.getItem('nazokake_evaluated')) || [];

async function logEvent(eventName, tabName = "") {
    let duration = 0; if (eventName === 'page_leave') duration = (Date.now() - sessionStartTime) / 1000;
    try { await fetch(`${API_BASE}/metrics/log`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ user_slug: userSlug, event_name: eventName, duration: duration, tab_name: tabName }) }); } catch (e) {}
}

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container'); if (!container) return;
    const toast = document.createElement('div'); const bg = type === 'warning' ? 'bg-[#902A19]' : 'bg-[#C5B358]';
    toast.className = `${bg} text-white px-6 py-3 rounded-full shadow-lg transform transition-all duration-300 -translate-y-10 opacity-0 flex items-center gap-2 font-bold text-sm pointer-events-auto z-50`;
    toast.innerHTML = `<span>${type === 'warning' ? '⚠️' : '✨'}</span><span class="${type !== 'warning' ? 'text-gray-900' : ''}">${message}</span>`;
    container.appendChild(toast); requestAnimationFrame(() => toast.classList.remove('-translate-y-10', 'opacity-0'));
    setTimeout(() => { toast.classList.add('opacity-0', '-translate-y-2'); setTimeout(() => toast.remove(), 300); }, 3000);
}

function switchTab(tabId) {
    document.querySelectorAll('.view-section').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
    document.getElementById('view-' + tabId)?.classList.add('active'); document.getElementById('tab-' + tabId)?.classList.add('active');
    logEvent('tab_click', tabId);
    if (tabId === 'feed' && !isUserFeedLoaded) { loadUserFeed(); }
}

async function shareText(odai, toku, kokoro, score, isHuman) {
    const intro = isHuman ? "私の自作なぞかけ！" : "からくりAIのなぞかけ！";
    const shareText = `${intro}\n\nお題：「${odai}」\n「${odai}」とかけて、\n「${toku}」ととく。\nそのこころは、\n${kokoro}\n\n分析官の評価: ⭐ ${score}/5.0\n\n#謎掛け学術振興会\n`;
    logEvent('share_sns');
    if (navigator.share) { try { await navigator.share({ title: '謎掛け学術振興会', text: shareText, url: APP_URL }); } catch (e) {} } else {
        try { await navigator.clipboard.writeText(shareText + "\n" + APP_URL); showToast("✨ なぞかけをコピーしました！"); setTimeout(() => { window.open(`https://twitter.com/intent/tweet?text=${encodeURIComponent(shareText + "\n" + APP_URL)}`, '_blank'); }, 500); } catch (e) { showToast("コピーに失敗しました", "warning"); }
    }
}
async function shareTextResult(type) {
    if (type === 'gen') shareText(document.getElementById('resHint').innerText, document.getElementById('resToku').innerText, document.getElementById('resKokoro').innerText, document.getElementById('resScore').innerText, false);
    else if (type === 'human') shareText(document.getElementById('hResHint').innerText, document.getElementById('hResToku').innerText, document.getElementById('hResKokoro').innerText, document.getElementById('hResScore').innerText, true);
}

async function startGeneration() {
    const odai = document.getElementById('odaiInput')?.value.trim(); if (!odai) { showError("お題を入力してください！"); return; }
    if(document.getElementById('generateBtn')) document.getElementById('generateBtn').disabled = true; document.getElementById('result-card')?.classList.add('hidden'); document.getElementById('error-card')?.classList.add('hidden'); document.getElementById('loading')?.classList.remove('hidden'); if(document.getElementById('statusMsg')) document.getElementById('statusMsg').innerText = "からくりが作動中...";
    const existingEval = document.getElementById('gen-eval-container'); if(existingEval) existingEval.remove();
    logEvent('generate_requested');
    try { const res = await fetch(`${API_BASE}/generate`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ odai: odai }) }); if (!res.ok) throw new Error("通信エラー"); const data = await res.json(); pollStatus(data.task_id); } catch (e) { showError(e.message); }
}
async function pollStatus(taskId) { try { const res = await fetch(`${API_BASE}/status/${taskId}`); const data = await res.json(); if (data.status === 'completed' && data.eval_status === 'completed') { document.getElementById('loading')?.classList.add('hidden'); if(document.getElementById('generateBtn')) document.getElementById('generateBtn').disabled = false; showResult(data, taskId); } else if (data.status === 'error' || data.eval_status === 'error') { throw new Error(data.message || "エラー"); } else { setTimeout(() => pollStatus(taskId), 2000); } } catch (e) { showError(e.message); } }
function showResult(data, taskId) {
    const result = data.result || {}; const scores = data.scores || {}; const odai = data.odai || document.getElementById('odaiInput')?.value.trim() || "";
    if(document.getElementById('resHint')) document.getElementById('resHint').innerText = odai; if(document.getElementById('resToku')) document.getElementById('resToku').innerText = result.toku || ""; if(document.getElementById('resKokoro')) document.getElementById('resKokoro').innerText = result.kokoro || ""; if(document.getElementById('resScore')) document.getElementById('resScore').innerText = (data.s_total || 0).toFixed(2);
    const resReasoningEl = document.getElementById('resReasoning'); if(resReasoningEl) resReasoningEl.innerHTML = `<div class="mb-3"><strong>【からくりの思考】</strong><br><span class="text-gray-700">${result.hint || ""}</span></div><div><strong>【講評】</strong><br><span class="text-gray-700">${data.reasoning || ""}</span></div>`;
    const ctx = document.getElementById('radarChart')?.getContext('2d');
    if(ctx) { const chartData = [scores.S_sur||0.5, scores.S_tech||0.5, scores.S_emo||0.5, scores.S_rhy||0.5, scores.S_sensory||0.5, scores.S_visual||0.5, scores.S_ontology||0.5, scores.S_cultural||0.5, scores.S_cm||0.5, scores.S_prosody||0.5, scores.S_nat||0.5, 0.0]; if (myRadarChart) myRadarChart.destroy(); myRadarChart = new Chart(ctx, { type: 'radar', data: { labels: ['意外性', '技巧', '情緒', 'リズム', '感覚', '視覚', '存在論', '文化', '概念', '韻律', '自然さ', '人間評価'], datasets: [{ data: chartData, backgroundColor: 'rgba(197, 179, 88, 0.2)', borderColor: 'rgba(197, 179, 88, 1)', borderWidth: 2 }] }, options: { scales: { r: { min: 0, max: 1.0, ticks: { display: false }, pointLabels: { font: { size: 9, family: "sans-serif" } } } }, plugins: { legend: { display: false } } } }); }
    document.getElementById('result-card')?.classList.remove('hidden');
}
function showError(msg) { document.getElementById('loading')?.classList.add('hidden'); if(document.getElementById('generateBtn')) document.getElementById('generateBtn').disabled = false; const errCard = document.getElementById('error-card'); if(errCard) { errCard.innerText = `🚨 エラー: ${msg}`; errCard.classList.remove('hidden'); } else { showToast(msg, "warning"); } }

async function submitHumanRiddle() {
    const odai = document.getElementById('hOdai')?.value.trim(); const toku = document.getElementById('hToku')?.value.trim(); let kokoro = document.getElementById('hKokoro')?.value.trim();
    if (!odai || !toku || !kokoro) { showToast("⚠️ すべて入力してください", "warning"); return; }
    const nz = `「${odai}」とかけて、「${toku}」と解く。\nその心は、${kokoro}`;
    if(document.getElementById('humanSubmitBtn')) document.getElementById('humanSubmitBtn').disabled = true; document.getElementById('human-result-card')?.classList.add('hidden'); document.getElementById('human-loading')?.classList.remove('hidden');
    logEvent('human_submit');
    try { const res = await fetch(`${API_BASE}/submit_human`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ odai: odai, nazokake_text: nz, parent_id: null }) }); const data = await res.json(); pollHumanStatus(data.doc_id, odai, toku, kokoro); } catch (e) { showToast(e.message, "warning"); }
}
async function pollHumanStatus(taskId, odai, toku, kokoro) { try { const res = await fetch(`${API_BASE}/status/${taskId}`); const data = await res.json(); if (data.status === 'completed') { document.getElementById('human-loading')?.classList.add('hidden'); if(document.getElementById('humanSubmitBtn')) document.getElementById('humanSubmitBtn').disabled = false; showHumanResult(data, odai, toku, kokoro); } else { setTimeout(() => pollHumanStatus(taskId, odai, toku, kokoro), 2000); } } catch (e) { showToast(e.message, "warning"); } }
function showHumanResult(data, odai, toku, kokoro) {
    const scores = data.scores || {};
    if(document.getElementById('hResHint')) document.getElementById('hResHint').innerText = odai; if(document.getElementById('hResToku')) document.getElementById('hResToku').innerText = toku; if(document.getElementById('hResKokoro')) document.getElementById('hResKokoro').innerText = kokoro; if(document.getElementById('hResScore')) document.getElementById('hResScore').innerText = (data.s_total || 0).toFixed(2);
    if(document.getElementById('hResReasoning')) document.getElementById('hResReasoning').innerHTML = `<span class="text-gray-700">${data.reasoning || "なし"}</span>`;
    const ctx = document.getElementById('humanRadarChart')?.getContext('2d');
    if(ctx) { const chartData = [scores.S_sur||0.5, scores.S_tech||0.5, scores.S_emo||0.5, scores.S_rhy||0.5, scores.S_sensory||0.5, scores.S_visual||0.5, scores.S_ontology||0.5, scores.S_cultural||0.5, scores.S_cm||0.5, scores.S_prosody||0.5, scores.S_nat||0.5, data.s_total?data.s_total/5:0.5]; if (humanRadarChart) humanRadarChart.destroy(); humanRadarChart = new Chart(ctx, { type: 'radar', data: { labels: ['意外性', '技巧', '情緒', 'リズム', '感覚', '視覚', '存在論', '文化', '概念', '韻律', '自然さ', '総合'], datasets: [{ data: chartData, backgroundColor: 'rgba(91, 129, 36, 0.2)', borderColor: 'rgba(91, 129, 36, 1)', borderWidth: 2 }] }, options: { scales: { r: { min: 0, max: 1.0, ticks:{display:false}, pointLabels: { font: { size: 9, family: "sans-serif" } } } }, plugins: { legend: { display: false } } } }); }
    document.getElementById('human-result-card')?.classList.remove('hidden'); showToast("✨ 鑑定完了！");
}

let lastDocId = null;
let isFetchingFeed = false;
let hasMoreFeed = true;
let feedObserver = null;

function loadUserFeed() {
    lastDocId = null;
    hasMoreFeed = true;
    isUserFeedLoaded = true;
    document.getElementById('feed-container').innerHTML = '';
    setupIntersectionObserver();
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

async function fetchNextFeedBatch() {
    if (isFetchingFeed || !hasMoreFeed) return;
    isFetchingFeed = true;
    const sentinel = document.getElementById('feed-sentinel');
    sentinel.innerHTML = '<div class="animate-bounce w-2 h-2 bg-[#C5B358] rounded-full"></div>';
    
    try {
        const queryParams = lastDocId ? `?last_doc_id=${lastDocId}&limit=5` : `?limit=5`;
        const res = await fetch(`${API_BASE}/feed/items` + queryParams);
        const data = await res.json();
        
        if (!data.items || data.items.length === 0) {
            hasMoreFeed = false;
            sentinel.innerHTML = '<p class="text-xs text-gray-400">すべて読み込みました</p>';
            if (!lastDocId) document.getElementById('feed-container').innerHTML = '<p class="text-center text-gray-500 bg-white/90 p-6 rounded-xl shadow-sm border border-[#C5B358]/50">現在、評価待ちの作品はありません。</p>';
        } else {
            data.items.forEach(item => renderFeedItem(item));
            lastDocId = data.items[data.items.length - 1].doc_id;
        }
    } catch (e) {
        showToast("読み込みエラー", "warning");
        sentinel.innerHTML = '<button onclick="fetchNextFeedBatch()" class="text-xs text-red-500 underline">再試行</button>';
    } finally {
        isFetchingFeed = false;
    }
}

function renderFeedItem(item) {
    const container = document.getElementById('feed-container');
    const docId = item.doc_id || item.id; const odai = item.odai || item.A_TITLE || "不明"; 
    let toku = item.result?.toku || ""; let kokoro = item.result?.kokoro || "";
    if (!toku && !kokoro && item.nazokake_text) { const tMatch = item.nazokake_text.match(/かけて、?「?(.*?)」?と[解と]く/); const kMatch = item.nazokake_text.match(/その[心こころ]は、?(.*)/); toku = tMatch ? tMatch[1] : ""; kokoro = kMatch ? kMatch[1] : item.nazokake_text; }
    const scores = item.scores || {}; const totalScore = (item.s_total || 0).toFixed(2); const reasoning = item.reasoning || "講評なし"; const chartId = `feed-chart-${docId}`;
    
    let evalUI = "";
    const isEvaluated = evaluatedItems.includes(docId);
    if (isEvaluated) {
        evalUI = `<div class="bg-gray-100 text-center py-4 mt-2 rounded-lg border border-gray-200 shadow-inner"><p class="text-gray-500 font-bold text-sm">✅ あなたはこの作品を評価済みです</p></div>`;
    } else {
        evalUI = `
        <div class="bg-[#FAF8F5] rounded-xl p-4 border border-[#C5B358]/50 shadow-inner mt-4">
            <label class="text-xs text-[#902A19] font-bold mb-2 block">1. 評価 (必須)</label>
            <input type="hidden" id="feed-score-${docId}" value="0">
            <div class="flex gap-2 mb-4">${[1,2,3,4,5].map(i => `<button onclick="setFeedRating('${docId}', ${i})" id="feed-star-${docId}-${i}" class="flex-1 py-2 border border-[#C5B358]/50 bg-white text-gray-400 rounded-md font-bold text-sm shadow-sm transition hover:scale-105">⭐${i}</button>`).join('')}</div>
            <details class="group mb-4"><summary class="text-xs text-[#5B8124] font-bold flex justify-between items-center cursor-pointer list-none bg-white p-2 border border-[#C5B358]/50 rounded shadow-sm hover:bg-gray-50 transition"><span>🖌️ 2. 赤ペン先生で添削 (任意)</span><span class="transition group-open:rotate-180 text-[#C5B358]">▼</span></summary><div class="pt-3 grid grid-cols-1 gap-2 bg-white p-3 rounded-b-lg border border-[#C5B358]/50 border-t-0 -mt-1"><div class="flex items-center gap-2"><span class="text-[10px] text-gray-700 font-bold w-8">お題:</span><input type="text" id="feed-odai-${docId}" value="${odai}" class="flex-1 px-2 py-1 text-xs border-b border-[#C5B358]/30 outline-none focus:border-[#C5B358]"></div><div class="flex items-center gap-2"><span class="text-[10px] text-gray-700 font-bold w-8">解き:</span><input type="text" id="feed-toku-${docId}" value="${toku}" class="flex-1 px-2 py-1 text-xs border-b border-[#C5B358]/30 outline-none focus:border-[#C5B358]"></div><div class="flex flex-col gap-1 mt-1"><span class="text-[10px] text-gray-700 font-bold">心:</span><textarea id="feed-kokoro-${docId}" rows="2" class="w-full px-2 py-1 text-xs border border-[#C5B358]/30 rounded outline-none focus:border-[#C5B358]">${kokoro}</textarea></div></div></details>
            <button onclick="submitUserEvaluation('${docId}')" class="w-full bg-[#2C3539] text-[#C5B358] py-3 rounded-lg text-sm font-bold shadow-md transition duration-200 hover:bg-gray-800">📤 確定して次へ</button>
        </div>`;
    }

    const html = `<div class="bg-white/95 backdrop-blur-sm rounded-xl shadow-md p-5 border-t-4 border-[#902A19] mb-6 transition-all duration-300 transform relative" id="feed-card-${docId}"><div class="text-center mb-4"><span class="inline-block px-3 py-1 bg-[#FAF8F5] text-[#902A19] rounded-full text-xs font-bold mb-3 border border-[#C5B358]/50 shadow-sm">お題：${odai}</span><p class="font-bold mb-2 text-lg">「<span class="text-[#902A19]">${odai}</span>」とかけて、</p><p class="font-bold mb-2 text-lg">「<span class="text-[#5B8124]">${toku}</span>」ととく。</p><p class="text-xs text-gray-600 mt-2">そのこころは、</p><p class="font-bold text-lg text-[#902A19]">${kokoro}</p></div><details class="group bg-[#FAF8F5] p-3 rounded-lg border border-[#C5B358]/50 cursor-pointer mb-2 shadow-sm"><summary class="font-bold text-[#902A19] text-xs flex justify-between items-center list-none outline-none"><span>⚙️ 分析官の講評 (${totalScore}/5.0)</span><span class="transition group-open:rotate-180 text-[#C5B358]">▼</span></summary><div class="mt-3 pt-3 border-t border-[#C5B358]/30 flex flex-col md:flex-row items-center gap-4"><div class="w-[140px] h-[140px] shrink-0"><canvas id="${chartId}"></canvas></div><p class="text-[11px] text-gray-700 leading-relaxed">${reasoning}</p></div></details>${evalUI}</div>`;
    container.insertAdjacentHTML('beforeend', html);
    
    setTimeout(() => { const ctx = document.getElementById(chartId); if(ctx) { const chartData = [scores.S_sur||0.5, scores.S_tech||0.5, scores.S_emo||0.5, scores.S_rhy||0.5, scores.S_sensory||0.5, scores.S_visual||0.5, scores.S_ontology||0.5, scores.S_cultural||0.5, scores.S_cm||0.5, scores.S_prosody||0.5, scores.S_nat||0.5, 0]; new Chart(ctx.getContext('2d'), { type: 'radar', data: { labels: ['意外性', '技巧', '情緒', 'リズム', '感覚', '視覚', '存在論', '文化', '概念', '韻律', '自然さ', '人間評価'], datasets: [{ data: chartData, backgroundColor: 'rgba(197, 179, 88, 0.2)', borderColor: 'rgba(197, 179, 88, 1)', borderWidth: 1, pointRadius: 0 }] }, options: { animation: false, scales: { r: { min: 0, max: 1.0, ticks: { display: false }, pointLabels: { font: { size: 6, family: "sans-serif" } } } }, plugins: { legend: { display: false } } } }); } }, 50);
}

function setFeedRating(docId, score) { document.getElementById(`feed-score-${docId}`).value = score; for(let i=1; i<=5; i++) { const btn = document.getElementById(`feed-star-${docId}-${i}`); if(i <= score) { btn.classList.add('bg-[#C5B358]', 'text-white'); btn.classList.remove('bg-white', 'text-gray-400'); } else { btn.classList.remove('bg-[#C5B358]', 'text-white'); btn.classList.add('bg-white', 'text-gray-400'); } } }

async function submitUserEvaluation(docId) {
    let score = parseFloat(document.getElementById(`feed-score-${docId}`).value); if (score === 0) { showToast("⚠️ 星を選択してください", "warning"); return; }
    const odai = document.getElementById(`feed-odai-${docId}`).value; const toku = document.getElementById(`feed-toku-${docId}`).value; const kokoro = document.getElementById(`feed-kokoro-${docId}`).value;
    logEvent('evaluate_feed');
    try { 
        await fetch(`${API_BASE}/feed/evaluate/${docId}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ odai: odai, toku: toku, kokoro: kokoro, s_total: score, human_comment: "", user_slug: userSlug }) }); 
        evaluatedItems.push(docId); localStorage.setItem('nazokake_evaluated', JSON.stringify(evaluatedItems));
        showToast("✨ 評価・添削ありがとうございます！"); 
        const card = document.getElementById(`feed-card-${docId}`); card.style.opacity = '0'; card.style.transform = 'scale(0.9) translateY(-20px)'; setTimeout(() => card.remove(), 300); 
    } catch (e) { showToast("エラー", 'warning'); }
}

// 📮 ご意見箱 (Feedback) 送信ロジック (ライトテーマ版)
function setFeedbackRating(score) {
    document.getElementById('feedback-score').value = score;
    for(let i=1; i<=5; i++) {
        const btn = document.getElementById(`fb-star-${i}`);
        if(i <= score) {
            btn.classList.add('bg-[#C5B358]', 'text-white', 'scale-110', 'border-[#C5B358]', 'shadow-md');
            btn.classList.remove('bg-white', 'text-gray-300', 'scale-100', 'border-gray-200', 'shadow-sm');
        } else {
            btn.classList.remove('bg-[#C5B358]', 'text-white', 'scale-110', 'border-[#C5B358]', 'shadow-md');
            btn.classList.add('bg-white', 'text-gray-300', 'scale-100', 'border-gray-200', 'shadow-sm');
        }
    }
}

async function submitFeedback() {
    const score = parseInt(document.getElementById('feedback-score').value);
    const comment = document.getElementById('feedback-comment').value.trim();
    
    if (score === 0 && comment === "") {
        showToast("⚠️ 評価かコメントのどちらかを入力してください", "warning");
        return;
    }
    
    document.getElementById('feedback-form-container').innerHTML = `
        <div class="text-center py-8 bg-[#FAF8F5] rounded-lg border border-[#C5B358]/50 shadow-inner">
            <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-[#C5B358] mx-auto mb-4"></div>
            <p class="text-gray-600 font-bold text-sm">通信鳩が手紙を運んでいます...</p>
        </div>
    `;
    
    try {
        const res = await fetch(`${API_BASE}/feedback`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ score: score, comment: comment, user_slug: userSlug })
        });
        
        if (!res.ok) throw new Error("送信失敗");
        
        logEvent('submit_feedback');
        
        document.getElementById('feedback-form-container').innerHTML = `
            <div class="text-center py-8 bg-green-50 rounded-lg border border-green-200 shadow-inner">
                <p class="text-3xl mb-2">✨</p>
                <p class="text-green-700 font-bold">貴重なご意見、確かに承りました！</p>
                <p class="text-gray-500 text-xs mt-2">今後のアプリ改善に役立たせていただきます。</p>
            </div>
        `;
    } catch (e) {
        showToast("送信に失敗しました。時間をおいてお試しください。", "warning");
        setTimeout(() => location.reload(), 2000);
    }
}

window.addEventListener('load', () => { logEvent('page_view'); });
window.addEventListener('beforeunload', () => { logEvent('page_leave'); });