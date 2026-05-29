import { initializeApp } from "https://www.gstatic.com/firebasejs/10.8.1/firebase-app.js";
import { getFirestore, collection, onSnapshot, doc } from "https://www.gstatic.com/firebasejs/10.8.1/firebase-firestore.js";

const firebaseConfig = {
    apiKey: "AIzaSyDVly4bOMt6KnsuTbm3QHLT4WiqkNH9_Ng",
    authDomain: "nazokakeapp-137e5.firebaseapp.com",
    projectId: "nazokakeapp-137e5"
};
const app = initializeApp(firebaseConfig);
const db = getFirestore(app);
const COLLECTION_NAME = "nazokake_items";

const URL_GENERATE = "https://nazokake-backend-862686676938.asia-northeast1.run.app/api/generate_ai"; 
const URL_SUBMIT_HUMAN = "https://nazokake-backend-862686676938.asia-northeast1.run.app/api/submit_human"; 
const URL_FEED = "https://nazokake-backend-862686676938.asia-northeast1.run.app/api/dojo_arena";
const URL_EVALUATE = "https://nazokake-backend-862686676938.asia-northeast1.run.app/api/evaluate";

// 💡 忘れ物1: 道場破りの「血統（parent_id）」を管理するグローバル変数
let currentParentId = null;

// --- タブ切り替え ---
const navBtns = document.querySelectorAll('.nav-btn');
const tabPanes = document.querySelectorAll('.tab-pane');
function switchTab(targetTabId) {
    navBtns.forEach(b => {
        if(b.getAttribute('data-target') === targetTabId) b.classList.add('active');
        else b.classList.remove('active');
    });
    tabPanes.forEach(p => {
        if(p.id === targetTabId) p.classList.remove('hidden');
        else p.classList.add('hidden');
    });
}
navBtns.forEach(btn => {
    btn.addEventListener('click', () => {
        const target = btn.getAttribute('data-target');
        switchTab(target);
        if (target === 'view-timeline') {
            loadFeed();
        } else if (target !== 'view-evaluate') {
            // 自作鑑定以外のタブへ移動した場合は血統リセット
            currentParentId = null;
        }
        window.scrollTo(0, 0);
    });
});

// --- チャート描画（11軸用） ---
function drawRadarChart(canvas, scores) {
    if (canvas.chartInstance) canvas.chartInstance.destroy();
    const getScore = (val) => (val ? parseFloat(val) * 100 : 0);
    const dataValues = [
        getScore(scores.S_sur), getScore(scores.S_tech), getScore(scores.S_emo),
        getScore(scores.S_rhy), getScore(scores.S_sensory), getScore(scores.S_visual),
        getScore(scores.S_ontology), getScore(scores.S_cultural), getScore(scores.S_cm),
        getScore(scores.S_prosody), getScore(scores.S_nat)
    ];
    canvas.chartInstance = new Chart(canvas.getContext('2d'), {
        type: 'radar',
        data: {
            labels: ['意外性', '技巧性', '情動的連関', 'リズム', '身体性', '視覚', '飛躍度', '文化', 'メタファー', '韻律', '納得感'],
            datasets: [{ data: dataValues, backgroundColor: 'rgba(147, 112, 219, 0.25)', borderColor: '#9370DB', pointBackgroundColor: '#9370DB', pointBorderColor: '#fff', borderWidth: 2 }]
        },
        options: { responsive: true, maintainAspectRatio: false, scales: { r: { angleLines: { color: 'rgba(0,0,0,0.1)' }, grid: { color: 'rgba(0,0,0,0.1)' }, pointLabels: { color: '#333', font: { family: "'Noto Sans JP', sans-serif", size: 10, weight: 'bold' } }, ticks: { display: false }, suggestedMin: 0, suggestedMax: 100 } }, plugins: { legend: { display: false } } }
    });
}

// --- チャート描画（フィード用12軸） ---
function drawFeedRadarChart(canvas, scores, humanScoreNormalized) {
    const getScore = (val) => (val ? parseFloat(val) * 100 : 0);
    const dataValues = [
        humanScoreNormalized,
        getScore(scores.S_sur), getScore(scores.S_tech), getScore(scores.S_emo),
        getScore(scores.S_rhy), getScore(scores.S_sensory), getScore(scores.S_visual),
        getScore(scores.S_ontology), getScore(scores.S_cultural), getScore(scores.S_cm),
        getScore(scores.S_prosody), getScore(scores.S_nat)
    ];
    new Chart(canvas.getContext('2d'), {
        type: 'radar',
        data: {
            labels: ['人間の評価', '意外性', '技巧性', '情動的連関', 'リズム', '身体性', '視覚', '飛躍度', '文化', 'メタファー', '韻律', '納得感'],
            datasets: [{ data: dataValues, backgroundColor: 'rgba(255, 177, 0, 0.15)', borderColor: '#FFB100', pointBackgroundColor: '#FFB100', pointBorderColor: '#fff', borderWidth: 2 }]
        },
        options: { responsive: true, maintainAspectRatio: false, scales: { r: { angleLines: { color: 'rgba(0,0,0,0.1)' }, grid: { color: 'rgba(0,0,0,0.1)' }, pointLabels: { color: '#333', font: { family: "'Noto Sans JP', sans-serif", size: 9, weight: 'bold' } }, ticks: { display: false }, suggestedMin: 0, suggestedMax: 100 } }, plugins: { legend: { display: false } } }
    });
}

// --- 結果表示テンプレートの構築 ---
function renderResult(targetAreaId, inputSectionId, data) {
    const area = document.getElementById(targetAreaId);
    area.innerHTML = ''; 
    const template = document.getElementById('result-template').content.cloneNode(true);
    
    // AIの改行をそのまま活かす（変なReplaceを削除）
    let cleanedText = (data.nazokake_text || "").replace(/\*\*/g, "");
    template.querySelector('.output-text').innerText = cleanedText;
    
    let cleanedReasoning = (data.reasoning || "講評データなし").replace(/\*\*/g, "");
    template.querySelector('.ai-feedback').innerText = cleanedReasoning;
    
    const canvas = template.querySelector('.radarChart');
    
    const stars = template.querySelectorAll('.star-clickable');
    let isEvaluated = false;
    stars.forEach(star => {
        star.addEventListener('click', async () => {
            if (isEvaluated) return;
            const selectValue = parseInt(star.getAttribute('data-value'));
            stars.forEach(s => {
                if(parseInt(s.getAttribute('data-value')) <= selectValue) s.classList.add('active');
                else s.classList.remove('active');
            });
            
            const evalLabel = template.querySelector('.eval-label') || area.querySelector('.eval-label');
            try {
                const res = await fetch(URL_EVALUATE, {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ doc_id: data.doc_id, user_score: selectValue })
                });
                if(!res.ok) throw new Error("送信エラー");
                isEvaluated = true;
                if(evalLabel) {
                    evalLabel.innerText = "評価送信完了！(RLHF蓄積)";
                    evalLabel.style.color = "var(--matcha-green)";
                }
            } catch(e) {
                alert("評価の送信に失敗しました");
            }
        });
    });

    template.querySelector('.dojo-btn-action').addEventListener('click', () => {
        document.getElementById('eval-odai').value = data.A_TITLE || data.odai || "";
        currentParentId = data.doc_id;
        switchTab('view-evaluate');
        document.getElementById('eval-toku').focus();
    });

    const btnShare = template.querySelector('.btn-share-x');
    if (btnShare) {
        btnShare.addEventListener('click', () => {
            const odaiText = data.A_TITLE || data.odai || "お題不明";
            const scoreText = (data.total_score || data.s_total) ? (data.total_score || data.s_total).toFixed(2) : "鑑定中";
            const text = `【お題：${odaiText}】\n${cleanedText}\n\n🤖 AI分析官の総合点: ${scoreText} / 5.00\n\n#謎掛け学術振興会 #AIなぞかけ`;
            window.open(`https://x.com/intent/tweet?text=${encodeURIComponent(text)}`, '_blank');
        });
    }

    area.appendChild(template);
    
    // 💡 修正の核心：チャートを描画する「前」に要素を表示状態(hidden解除)にする！
    document.getElementById(inputSectionId).classList.add('hidden');
    area.classList.remove('hidden');
    
    // 表示されてから描画することで、Chart.jsが正しいサイズを認識して表示される
    drawRadarChart(canvas, data.scores || {});
    
    area.querySelector('.btn-reset').addEventListener('click', () => {
        area.classList.add('hidden');
        document.getElementById(inputSectionId).classList.remove('hidden');
        currentParentId = null;
    });
}

// --- 通信と監視の共通処理 ---
async function processRequest(url, payload, targetAreaId, inputSectionId) {
    const loader = document.getElementById('loading-overlay');
    const loadingText = document.getElementById('loading-text');
    loadingText.innerText = 'AI分析官が多角的に鑑定中...';
    loader.classList.remove('hidden');
    
    try {
        const res = await fetch(url, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload) });
        if (!res.ok) throw new Error(`[${res.status}エラー] ${await res.text()}`);
        
        const data = await res.json();
        if (!data.doc_id) throw new Error("ドキュメントIDが見つかりません。");

        const unsub = onSnapshot(doc(db, COLLECTION_NAME, data.doc_id), (docSnap) => {
            if (docSnap.exists()) {
                const resultData = docSnap.data();
                resultData.doc_id = docSnap.id;
                
                const isCompleted = resultData.status === 2 || resultData.status === "completed" || resultData.eval_status === "completed";
                const hasScores = resultData.scores && Object.keys(resultData.scores).length > 0;
                
                if (isCompleted && hasScores) {
                    loader.classList.add('hidden');
                    renderResult(targetAreaId, inputSectionId, resultData);
                    unsub();
                } else if (resultData.status === -1 || resultData.status === "error" || resultData.eval_status === "error") {
                    alert("Firestore上でエラー終了しました。");
                    loader.classList.add('hidden');
                    document.getElementById(inputSectionId).classList.remove('hidden');
                    unsub();
                }
            }
        });
    } catch (e) {
        alert("🚨 鑑定通信エラー:\n" + e.message);
        console.error(e);
        loader.classList.add('hidden');
        document.getElementById(inputSectionId).classList.remove('hidden');
    }
}

// 💡 1. AI生成の実行
document.getElementById('btn-generate').addEventListener('click', async () => {
    const odai = document.getElementById('gen-odai-input').value.trim();
    if (!odai) return alert('お題を入力してください');
    
    const loader = document.getElementById('loading-overlay');
    const loadingText = document.getElementById('loading-text');
    document.getElementById('gen-input-section').classList.add('hidden');
    
    loadingText.innerText = '【1/2】AIがなぞかけを考案中...';
    loader.classList.remove('hidden');
    
    try {
        const genRes = await fetch(URL_GENERATE, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ odai: odai }) });
        if (!genRes.ok) throw new Error(`[${genRes.status}] ${await genRes.text()}`);
        
        const genData = await genRes.json();
        const generatedText = genData.nazokake;
        if (!generatedText) throw new Error("テキストが生成されませんでした。");
        
        loader.classList.add('hidden');
        // AI生成作品も、万が一の道場破り派生なら血統を継承
        processRequest(URL_SUBMIT_HUMAN, { odai: odai, nazokake_text: generatedText, parent_id: currentParentId }, 'gen-result-area', 'gen-input-section');
    } catch (e) {
        alert("🚨 生成エラー発生:\n" + e.message);
        console.error(e);
        loader.classList.add('hidden');
        document.getElementById('gen-input-section').classList.remove('hidden');
    }
});

// 💡 2. 自作鑑定の実行
document.getElementById('btn-evaluate').addEventListener('click', () => {
    const odai = document.getElementById('eval-odai').value.trim();
    const toku = document.getElementById('eval-toku').value.trim();
    const kokoro = document.getElementById('eval-kokoro').value.trim();
    
    if (!odai || !toku || !kokoro) return alert('すべての項目を入力してください');
    
    const nazokake_text = `「${odai}」とかけて、「${toku}」と解く。その心は、『${kokoro}』`;
    // 血統（parent_id）を含めて送信
    processRequest(URL_SUBMIT_HUMAN, { odai: odai, nazokake_text: nazokake_text, parent_id: currentParentId }, 'eval-result-area', 'eval-input-section');
});

// 💡 3. フィードの読み込み
async function loadFeed() {
    const container = document.getElementById('timeline-container');
    container.innerHTML = '<div class="loader" style="margin: 20px auto;"></div><p style="text-align:center; color: var(--azuki-red);">新着作品を取得中...</p>';
    
    try {
        const res = await fetch(URL_FEED);
        if (!res.ok) throw new Error("フィードの取得に失敗しました");
        const data = await res.json();
        const items = data.arena_items || [];
        container.innerHTML = '';
        
        if (items.length === 0) {
            container.innerHTML = '<p style="text-align:center;">まだ作品がありません。</p>';
            return;
        }

        items.forEach(item => {
            if (!item.nazokake_text) return;
            
            const card = document.createElement('div');
            card.className = 'feed-card';
            
            const odai = item.A_TITLE || "お題不明";
            let text = item.nazokake_text.replace(/\*\*/g, "").replace("と解く、", "と解く、\n");
            const aiScore = (item.total_score || item.s_total) ? (item.total_score || item.s_total).toFixed(2) : "鑑定中";
            
            let humanScoreNormalized = 0;
            const evals = item.user_evaluations || [];
            const humanEvals = evals.filter(e => !e.is_synthetic).map(e => e.user_score || 0);
            if (humanEvals.length > 0) {
                const avg = humanEvals.reduce((a, b) => a + b, 0) / humanEvals.length;
                humanScoreNormalized = (avg / 5) * 100;
            }
            
            card.innerHTML = `
                <div class="feed-header">お題：${odai}</div>
                <div class="feed-body">${text}</div>
                <div class="feed-score">🤖 AI分析官の総合点: ${aiScore} / 5.00</div>
                
                <div class="feed-chart-wrapper" style="width: 100%; height: 250px; margin: 1rem 0;">
                    <canvas class="feed-radar-chart"></canvas>
                </div>
                
                <div class="feed-actions" style="flex-wrap: wrap; gap: 10px;">
                    <span class="action-msg">この作品を評価して育てる：</span>
                    <div class="feed-stars" data-id="${item.doc_id}">
                        <span class="feed-star" data-val="1">★</span>
                        <span class="feed-star" data-val="2">★</span>
                        <span class="feed-star" data-val="3">★</span>
                        <span class="feed-star" data-val="4">★</span>
                        <span class="feed-star" data-val="5">★</span>
                    </div>
                    <button class="dojo-btn-action feed-dojo-btn" style="margin-left: auto;">🥊 この作品で道場破り</button>
                </div>
            `;
            container.appendChild(card);
            
            const canvas = card.querySelector('.feed-radar-chart');
            drawFeedRadarChart(canvas, item.scores || {}, humanScoreNormalized);
            
            // フィードからの道場破り連動（血統セットとフォーカス）
            card.querySelector('.feed-dojo-btn').addEventListener('click', () => {
                document.getElementById('eval-odai').value = odai;
                currentParentId = item.doc_id; // 血統セット
                switchTab('view-evaluate');
                document.getElementById('eval-toku').focus();
            });
        });
        
        // フィードの星評価送信
        document.querySelectorAll('.feed-stars').forEach(starBox => {
            const stars = starBox.querySelectorAll('.feed-star');
            const docId = starBox.getAttribute('data-id');
            let isEvaluated = false;
            
            stars.forEach(star => {
                star.addEventListener('click', async () => {
                    if (isEvaluated) return;
                    const score = parseInt(star.getAttribute('data-val'));
                    stars.forEach(s => {
                        if(parseInt(s.getAttribute('data-val')) <= score) s.classList.add('active');
                        else s.classList.remove('active');
                    });
                    
                    try {
                        const res = await fetch(URL_EVALUATE, {
                            method: 'POST', headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({ doc_id: docId, user_score: score })
                        });
                        if(!res.ok) throw new Error("送信エラー");
                        
                        isEvaluated = true;
                        const actionArea = starBox.parentElement;
                        actionArea.style.background = "rgba(107, 142, 35, 0.15)";
                        actionArea.querySelector('.action-msg').innerText = "評価を送信しました！（RLHF蓄積）";
                        actionArea.querySelector('.action-msg').style.color = "var(--matcha-green)";
                        actionArea.querySelector('.action-msg').style.fontWeight = "bold";
                    } catch(e) {
                        alert("評価の送信に失敗しました");
                    }
                });
            });
        });
        
    } catch (e) {
        container.innerHTML = '<p style="color:red; text-align:center;">フィードの読み込みに失敗しました。</p>';
        console.error(e);
    }
}





