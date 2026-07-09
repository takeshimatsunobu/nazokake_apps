// frontend/public/ui/feed.js
// 道場破りフィードの描画ロジック（View）。
// app.js（Controller）から window.uiRenderFeed(feedItems) で呼び出される。

// 単一作品カードを feed-container に描画する（内部関数）
function renderFeedItem(item) {
    const container = document.getElementById('feed-container');
    const docId = item.doc_id || item.id; const odai = item.odai || item.A_TITLE || "不明";
    let toku = item.result?.toku || ""; let kokoro = item.result?.kokoro || "";
    if (!toku && !kokoro && item.nazokake_text) { const tMatch = item.nazokake_text.match(/かけて、?「?(.*?)」?と[解と]く/); const kMatch = item.nazokake_text.match(/その[心こころ]は、?(.*)/); toku = tMatch ? tMatch[1] : ""; kokoro = kMatch ? kMatch[1] : item.nazokake_text; }
    const scores = item.scores || {}; const totalScore = (item.s_total || 0).toFixed(2); const critiqueHtml = window.uiBuildCritiqueHtml(item); const chartId = `feed-chart-${docId}`;

    let evalUI = "";
    const isEvaluated = window.appState.evaluatedItems.includes(docId);
    if (isEvaluated) {
        evalUI = `<div class="bg-gray-100 text-center py-4 mt-2 rounded-lg border border-gray-200 shadow-inner"><p class="text-gray-500 font-bold text-sm">✅ あなたはこの作品を評価済みです</p></div>`;
    } else {
        evalUI = `
        <div class="bg-[#FAF8F5] rounded-xl p-4 border border-[#C5B358]/50 shadow-inner mt-4">
            <label class="text-xs text-[#902A19] font-bold mb-2 block">1. 評価 (必須)</label>
            <input type="hidden" id="feed-score-${docId}" value="0">
            <div class="flex gap-2 mb-4">${[1,2,3,4,5].map(i => `<button onclick="setFeedRating('${docId}', ${i})" id="feed-star-${docId}-${i}" class="flex-1 py-2 border border-[#C5B358]/50 bg-white text-gray-400 rounded-md font-bold text-sm shadow-sm transition hover:scale-105">⭐${i}</button>`).join('')}</div>
            <textarea id="feed-comment-${docId}" rows="2" placeholder="なぜこの評価にしたか（任意・コメント）" class="w-full text-xs px-2 py-1.5 mb-4 bg-white border border-[#C5B358]/40 rounded-md focus:outline-none focus:ring-1 focus:ring-[#C5B358] resize-none"></textarea>
            <details class="group mb-4"><summary class="text-xs text-[#5B8124] font-bold flex justify-between items-center cursor-pointer list-none bg-white p-2 border border-[#C5B358]/50 rounded shadow-sm hover:bg-gray-50 transition"><span>🖌️ 2. 赤ペン先生で添削 (任意)</span><span class="transition group-open:rotate-180 text-[#C5B358]">▼</span></summary><div class="pt-3 grid grid-cols-1 gap-2 bg-white p-3 rounded-b-lg border border-[#C5B358]/50 border-t-0 -mt-1"><div class="flex items-center gap-2"><span class="text-[10px] text-gray-700 font-bold w-8">お題:</span><input type="text" id="feed-odai-${docId}" value="${odai}" class="flex-1 px-2 py-1 text-xs border-b border-[#C5B358]/30 outline-none focus:border-[#C5B358]"></div><div class="flex items-center gap-2"><span class="text-[10px] text-gray-700 font-bold w-8">解き:</span><input type="text" id="feed-toku-${docId}" value="${toku}" class="flex-1 px-2 py-1 text-xs border-b border-[#C5B358]/30 outline-none focus:border-[#C5B358]"></div><div class="flex flex-col gap-1 mt-1"><span class="text-[10px] text-gray-700 font-bold">心:</span><textarea id="feed-kokoro-${docId}" rows="2" class="w-full px-2 py-1 text-xs border border-[#C5B358]/30 rounded outline-none focus:border-[#C5B358]">${kokoro}</textarea></div></div></details>
            <button onclick="submitUserEvaluation('${docId}')" class="w-full bg-[#2C3539] text-[#C5B358] py-3 rounded-lg text-sm font-bold shadow-md transition duration-200 hover:bg-gray-800">📤 確定して次へ</button>
        </div>`;
    }

    const html = `<div class="bg-white/95 backdrop-blur-sm rounded-xl shadow-md p-5 border-t-4 border-[#902A19] mb-6 transition-all duration-300 transform relative" id="feed-card-${docId}"><div class="text-center mb-4"><span class="inline-block px-3 py-1 bg-[#FAF8F5] text-[#902A19] rounded-full text-xs font-bold mb-3 border border-[#C5B358]/50 shadow-sm">お題：${odai}</span><p class="font-bold mb-2 text-lg">「<span class="text-[#902A19]">${odai}</span>」とかけて、</p><p class="font-bold mb-2 text-lg">「<span class="text-[#5B8124]">${toku}</span>」ととく。</p><p class="text-xs text-gray-600 mt-2">そのこころは、</p><p class="font-bold text-lg text-[#902A19]">${kokoro}</p></div><details class="group bg-[#FAF8F5] p-3 rounded-lg border border-[#C5B358]/50 cursor-pointer mb-2 shadow-sm"><summary class="font-bold text-[#902A19] text-xs flex justify-between items-center list-none outline-none"><span>⚙️ 分析官の講評 (${totalScore}/5.0)</span><span class="transition group-open:rotate-180 text-[#C5B358]">▼</span></summary><div class="mt-3 pt-3 border-t border-[#C5B358]/30 flex flex-col md:flex-row items-center gap-4"><div class="w-[140px] h-[140px] shrink-0"><canvas id="${chartId}"></canvas></div><div class="text-[11px] text-gray-700 leading-relaxed flex-1">${critiqueHtml}</div></div></details>${evalUI}</div>`;
    container.insertAdjacentHTML('beforeend', html);

    setTimeout(() => { const ctx = document.getElementById(chartId); if(ctx) { const chartData = [scores.S_sur||0.5, scores.S_tech||0.5, scores.S_emo||0.5, scores.S_rhy||0.5, scores.S_sensory||0.5, scores.S_visual||0.5, scores.S_ontology||0.5, scores.S_cultural||0.5, scores.S_cm||0.5, scores.S_prosody||0.5, scores.S_nat||0.5, 0]; new Chart(ctx.getContext('2d'), { type: 'radar', data: { labels: ['意外性', '技巧', '情緒', 'リズム', '感覚', '視覚', '存在論', '文化', '概念', '韻律', '自然さ', '人間評価'], datasets: [{ data: chartData, backgroundColor: 'rgba(197, 179, 88, 0.2)', borderColor: 'rgba(197, 179, 88, 1)', borderWidth: 1, pointRadius: 0 }] }, options: { animation: false, scales: { r: { min: 0, max: 1.0, ticks: { display: false }, pointLabels: { font: { size: 6, family: "sans-serif" } } } }, plugins: { legend: { display: false } } } }); } }, 50);
}

// フィード（作品の配列）をまとめて描画する公開エントリポイント
window.uiRenderFeed = function(feedItems) {
    if (!feedItems) return;
    feedItems.forEach(item => renderFeedItem(item));
};

// 道場破りカードの星評価の選択状態を反映する（onclick="setFeedRating(docId, i)" から呼ばれる）
window.setFeedRating = function(docId, score) {
    document.getElementById(`feed-score-${docId}`).value = score;
    for(let i=1; i<=5; i++) {
        const btn = document.getElementById(`feed-star-${docId}-${i}`);
        if(i <= score) { btn.classList.add('bg-[#C5B358]', 'text-white'); btn.classList.remove('bg-white', 'text-gray-400'); }
        else { btn.classList.remove('bg-[#C5B358]', 'text-white'); btn.classList.add('bg-white', 'text-gray-400'); }
    }
};

// === フィードのView制御（app.js の loadUserFeed / fetchNextFeedBatch / submitUserEvaluation から移管） ===
// Controller(app.js) は #feed-container / #feed-sentinel の中身を直接いじらず、以下を呼ぶだけにする。
// ※ #feed-sentinel は #feed-container の兄弟要素なので、uiFeedClear() で監視ノードは破壊されない。

// フィード一覧をクリアする（再読み込みの起点）。
window.uiFeedClear = function() {
    const c = document.getElementById('feed-container');
    if (c) c.innerHTML = '';
};

// 追加読み込み中: sentinel にローディングのドットアニメを表示する。
window.uiFeedShowLoading = function() {
    const s = document.getElementById('feed-sentinel');
    if (s) s.innerHTML = '<div class="animate-bounce w-2 h-2 bg-[#C5B358] rounded-full"></div>';
};

// 全件読み込み完了: sentinel に終端メッセージを表示する。
window.uiFeedShowEnd = function() {
    const s = document.getElementById('feed-sentinel');
    if (s) s.innerHTML = '<p class="text-xs text-gray-400">すべて読み込みました</p>';
};

// 作品が1件も無い場合: feed-container に空状態メッセージを表示する。
window.uiFeedShowEmpty = function() {
    const c = document.getElementById('feed-container');
    if (c) c.innerHTML = '<p class="text-center text-gray-500 bg-white/90 p-6 rounded-xl shadow-sm border border-[#C5B358]/50">現在、評価待ちの作品はありません。</p>';
};

// 読み込みエラー時: sentinel に「再試行」ボタンを表示する。
// onclick 文字列やグローバル依存を排し、addEventListener で onRetry コールバックを結線する。
window.uiFeedShowRetry = function(onRetry) {
    const s = document.getElementById('feed-sentinel');
    if (!s) return;
    s.innerHTML = '<button type="button" class="text-xs text-red-500 underline">再試行</button>';
    const btn = s.querySelector('button');
    if (btn && typeof onRetry === 'function') btn.addEventListener('click', onRetry);
};

// 評価フォームの入力値を読み取って返す（DOM読取はViewの責務）。
window.uiFeedGetEvaluationInput = function(docId) {
    const val = (id) => document.getElementById(id)?.value;
    return {
        score: parseFloat(val(`feed-score-${docId}`)) || 0,
        odai: val(`feed-odai-${docId}`) || '',
        toku: val(`feed-toku-${docId}`) || '',
        kokoro: val(`feed-kokoro-${docId}`) || '',
        comment: (val(`feed-comment-${docId}`) || '').trim(),
    };
};

// 評価済みカードをフェードアウトさせて取り除く（退場アニメ）。
window.uiFeedRemoveCard = function(docId) {
    const card = document.getElementById(`feed-card-${docId}`);
    if (!card) return;
    card.style.opacity = '0';
    card.style.transform = 'scale(0.9) translateY(-20px)';
    setTimeout(() => card.remove(), 300);
};
