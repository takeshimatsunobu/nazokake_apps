// frontend/public/ui/result.js
// 鑑定結果の描画ロジック（View）。
// APIレスポンスを受け取り、結果テキスト・講評・レーダーチャートを画面に描画する。
// app.js（Controller）から window.uiShowResult / window.uiShowGenResult で呼び出される。
//
// 外部依存:
//   - Chart  : index.html の CDN で読み込まれるグローバル。new Chart() をそのまま利用する。
//             生成済みインスタンスは window.appState に保持し、再描画時に destroy して
//             同一 canvas の再利用エラーを防ぐ。
//   - canvas : #radarChart / #humanRadarChart（index.html 内、本ファイルからは生成しない）
//   - window.appState  : チャートインスタンスの保持（state.js を app.js が公開）
//   - window.showToast : 完了トースト（ui/toast.js）

// --- 講評描画の共通ヘルパー（result.js / feed.js 共用。window 経由で公開） ---
// 11軸の表示ラベル（A-1 ルーブリックの軸定義に準拠）。
window.uiAxisLabels = {
    S_nat: '自然さ', S_tech: '技巧', S_rhy: 'リズム', S_prosody: '韻律',
    S_sur: '意外性', S_emo: '論理/納得感', S_cultural: '文化',
    S_visual: '視覚', S_sensory: '感覚', S_cm: 'クロスモーダル', S_ontology: '存在論'
};

// プレーンテキストのHTMLエスケープ（新形式の overall / axis_comments はプレーンテキストのため必須）。
window.uiEscapeHtml = function(s) {
    return String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
};

// 講評HTMLを構築する。後方互換の分岐:
//   新形式（overall / axis_comments あり） → 新デザインで描画（テキストはエスケープ）
//   旧形式（reasoning にHTML文字列）       → これまで通り reasoning をそのまま描画
window.uiBuildCritiqueHtml = function(data) {
    data = data || {};
    const hasNew = !!(data.overall || (data.axis_comments && Object.keys(data.axis_comments).length));
    if (hasNew) {
        const esc = window.uiEscapeHtml;
        const labels = window.uiAxisLabels;
        const comments = data.axis_comments || {};
        const scores = data.scores || {};
        const rows = Object.keys(labels)
            .filter(k => comments[k])
            .map(k => {
                const sc = (typeof scores[k] === 'number') ? scores[k].toFixed(2) : '-';
                return `<div class="mb-1"><span class="font-bold text-[#5B8124]">${labels[k]} (${sc})</span>: <span class="text-gray-700">${esc(comments[k])}</span></div>`;
            }).join('');
        return `<div class="text-left text-[11px] leading-relaxed">`
            + (data.overall ? `<p class="mb-2"><strong class="text-[#902A19]">総評:</strong> <span class="text-gray-700">${esc(data.overall)}</span></p>` : '')
            + (rows ? `<details class="group"><summary class="cursor-pointer text-[#5B8124] font-bold text-xs list-none outline-none">▼ 軸別の所見を見る</summary><div class="mt-2 pt-2 border-t border-[#C5B358]/30">${rows}</div></details>` : '')
            + `</div>`;
    }
    // 旧形式フォールバック: reasoning はHTML文字列のためそのまま描画。
    return `<span class="text-gray-700">${data.reasoning || "なし"}</span>`;
};

// === からくりAI生成結果の描画（Progressive Disclosure / Gemini & ELYZA 同格表示） ===
// 生成と評価が分離されているため、ポーリングのたびに本関数を呼び、入手済みデータでカードを更新する。
// 状態: gemini_generated(本文のみ・採点中) → gemini_completed(採点済) → llmjp_status:generated → all_completed。

// モデル別の人間評価フォーム（星1〜5＋送信）。Gemini / ELYZA で独立。提出済みなら御礼を表示。
function _genRatingHtml(key, label) {
    if (window._genSubmitted && window._genSubmitted[key]) {
        return `<div id="gen-rate-${key}" class="mt-3 pt-3 border-t border-[#C5B358]/30 text-center text-[#5B8124] font-bold text-sm py-1">✨ ${label}の評価ありがとうございました</div>`;
    }
    const r = (window._genRatings && window._genRatings[key]) || 0;
    const stars = [1, 2, 3, 4, 5].map(i => {
        const style = (i <= r) ? 'background-color:#C5B358;color:#fff;' : 'background-color:#fff;color:#d1d5db;';
        return `<button onclick="setGenRating('${key}',${i})" id="gen-star-${key}-${i}" style="${style}" class="flex-1 py-1.5 border border-[#C5B358]/50 rounded-md font-bold text-sm shadow-sm transition hover:scale-105">⭐${i}</button>`;
    }).join('');
    const comment = (window._genComments && window._genComments[key]) || '';
    return `<div id="gen-rate-${key}" class="mt-3 pt-3 border-t border-[#C5B358]/30">
        <label class="text-[11px] text-[#902A19] font-bold block mb-1">この ${label} の作品を評価 (任意)</label>
        <div class="flex gap-1 mb-2">${stars}</div>
        <textarea id="gen-comment-${key}" oninput="setGenComment('${key}', this.value)" rows="2" placeholder="なぜこの評価にしたか（任意・コメント）" class="w-full text-xs px-2 py-1.5 mb-2 bg-gray-50 border border-[#C5B358]/40 rounded-md focus:outline-none focus:ring-1 focus:ring-[#C5B358] resize-none">${window.uiEscapeHtml(comment)}</textarea>
        <button onclick="submitGenEvaluation('${key}')" class="w-full bg-[#2C3539] text-[#C5B358] py-1.5 rounded-md text-xs font-bold hover:bg-gray-800 transition">📤 ${label} の評価を送る</button>
    </div>`;
}

// 1モデル分の「同格カード」HTMLを組み立てる（派手な演出は避け、客観比較できる素朴な体裁）。
function _genModelCard(opts) {
    const esc = window.uiEscapeHtml;
    const r = opts.result || {};
    const hasBody = !!(r.toku || r.kokoro);
    const score = (opts.scoreData && typeof opts.scoreData.s_total === 'number' && opts.scoreData.s_total > 0)
        ? opts.scoreData.s_total.toFixed(2) : null;

    let body;
    if (opts.failed) {
        body = `<div class="py-6 text-center text-gray-400 text-sm">今回は生成をお休みしました</div>`;
    } else if (hasBody) {
        body = `<p class="font-bold text-lg leading-relaxed">
                    「<span class="text-[#902A19]">${esc(opts.odai || '')}</span>」とかけて、<br>
                    「<span class="text-[#5B8124]">${esc(r.toku || '')}</span>」ととく。
                </p>
                <p class="text-xs text-gray-500 mt-2">そのこころは、</p>
                <p class="font-bold text-[#902A19] mt-1 text-lg">${esc(r.kokoro || '')}</p>`;
    } else {
        body = `<div class="py-6 text-center text-gray-400 text-sm"><div class="animate-spin inline-block rounded-full h-6 w-6 border-b-2 border-[#C5B358] mb-2"></div><br>生成中...</div>`;
    }

    let evalBlock = '';
    if (!opts.failed && score) {
          const chartId = `chart-${opts.key}-${Date.now()}`;
          evalBlock = `<div class="text-center mt-3 pt-3 border-t border-[#C5B358]/30"><span class="text-xs text-gray-500">総合評価: </span><span class="text-2xl font-bold text-[#902A19]">${score}</span><span class="text-xs text-gray-500">/5.0</span></div>
              <div class="relative w-full max-w-[300px] mx-auto my-4"><canvas id="${chartId}"></canvas></div>
              <div class="mt-2">${window.uiBuildCritiqueHtml(opts.scoreData)}</div>`;
          
          setTimeout(() => {
              const ctx = document.getElementById(chartId);
              if (ctx) {
                  const s = opts.scoreData.scores || {};
                  const chartData = [s.S_sur||0.5, s.S_tech||0.5, s.S_emo||0.5, s.S_rhy||0.5, s.S_sensory||0.5, s.S_visual||0.5, s.S_ontology||0.5, s.S_cultural||0.5, s.S_cm||0.5, s.S_prosody||0.5, s.S_nat||0.5, 0];
                  new Chart(ctx.getContext('2d'), {
                      type: 'radar',
                      data: {
                          labels: ['意外性', '技巧', '情緒', 'リズム', '感覚', '視覚', '存在論', '文化', '概念', '韻律', '自然さ', '人間評価'],
                          datasets: [{ data: chartData, backgroundColor: 'rgba(197, 179, 88, 0.2)', borderColor: 'rgba(197, 179, 88, 1)', borderWidth: 1, pointRadius: 0 }]
                      },
                      options: { animation: false, scales: { r: { min: 0, max: 1.0, ticks: { display: false }, pointLabels: { font: { size: 6, family: "sans-serif" } } } }, plugins: { legend: { display: false } } }
                  });
              }
          }, 100);
    } else if (!opts.failed && hasBody) {
        // 本文は先行表示済み。スコア未到着（採点中）はローディングのみ出し、講評・チャート・星評価は出さない。
        evalBlock = `<div class="mt-3 pt-3 border-t border-[#C5B358]/30 text-center text-[#5B8124] text-xs font-bold flex items-center justify-center gap-2"><span class="animate-spin inline-block rounded-full h-4 w-4 border-b-2 border-[#5B8124]"></span><span class="animate-pulse">🔍 分析官が採点中...</span></div>`;
    }

    // モデル別の人間評価フォームは「採点完了後（score 確定後）」にのみ表示する。
    // 本文だけ先行表示中（採点中）は星評価を出さない。
    const ratingBlock = (hasBody && !opts.failed && score) ? _genRatingHtml(opts.key, opts.label) : '';

    return `<div id="gen-card-${opts.key}" class="bg-white/95 rounded-xl shadow p-4 border-t-4 ${opts.accent} flex flex-col">
        <div class="text-center mb-2"><span class="inline-block px-3 py-1 rounded-full text-[11px] font-bold ${opts.badge}">${opts.title}</span></div>
        <div class="text-center flex-1">${body}</div>
        ${evalBlock}
        ${ratingBlock}
    </div>`;
}

// 生成結果（Gemini・ELYZA）を同格カードで描画する。ポーリングのたびに呼ばれ、冪等に更新する。
window.uiRenderGenResult = function(data, taskId) {
    const card = document.getElementById('result-card');
    if (!card) return;
    card.classList.remove('hidden');

    // タスクIDが切り替わった（新しい生成が始まった）ら、評価状態を確実にリセットする。
    // 「別のお題で作る」を経由せず再生成した場合でも、前回の評価済みフラグを持ち越さない。
    if (taskId && window._genTaskId !== taskId) {
        window._genRatings = { gemini: 0, elyza: 0 };
        window._genSubmitted = { gemini: false, elyza: false };
        window._genComments = { gemini: '', elyza: '' };
        window._genTaskId = taskId;
    }

    // 既存の静的な単一結果マークアップ（最初の子div）は隠し、動的デュアルUIを使う
    const staticInner = card.querySelector(':scope > div');
    if (staticInner && staticInner.id !== 'gen-dual') staticInner.classList.add('hidden');

    let host = document.getElementById('gen-dual');
    if (!host) {
        host = document.createElement('div');
        host.id = 'gen-dual';
        card.insertBefore(host, card.firstChild);
        // 評価状態のリセットはタスクID変更検知（関数先頭）に一元化したのでここでは行わない。
        host.innerHTML = `
            <div id="gen-odai-master" class="mb-8"></div>
            <div id="gen-cards-grid" class="flex flex-col space-y-6"></div>
            <button id="gen-regen-btn" onclick="uiResetGenerator()" class="w-full mt-6 bg-[#902A19] text-white py-3 rounded-lg text-base font-bold shadow-md hover:bg-[#7a2315] hover:scale-[1.01] transition flex items-center justify-center gap-2">✨ 別のお題で作る</button>`;
    }

    // お題マスターヘッダー: 各AIカードの上位階層に、「今このお題で勝負中」と一目でわかる
    // 大きな独立見出しとして掲げる（カードと同列の小バッジからの昇格）。
    const odai = data.odai || document.getElementById('odaiInput')?.value.trim() || "";
    document.getElementById('gen-odai-master').innerHTML = `
        <div class="text-center bg-gradient-to-b from-[#FAF8F5] to-white rounded-2xl shadow-md border border-[#C5B358]/40 px-6 py-6 relative overflow-hidden">
            <div class="absolute top-0 left-0 w-full h-1.5 bg-gradient-to-r from-[#C5B358] via-[#902A19] to-[#5B8124]"></div>
            <p class="text-[11px] font-bold tracking-[0.3em] text-[#C5B358] mb-2">＼ 今回のお題 ／</p>
            <h2 class="text-3xl sm:text-4xl font-black text-[#902A19] leading-tight break-words">${window.uiEscapeHtml(odai)}</h2>
            <p class="text-xs text-gray-500 mt-3">この一題で、2つのAIが知恵を競います</p>
        </div>`;

    const geminiCard = _genModelCard({
        key: 'gemini', label: 'Gemini', title: '☁️ クラウドAI Gemini', accent: 'border-[#C5B358]', badge: 'bg-[#C5B358]/20 text-[#902A19]', odai: odai,
        result: (data.result_gemini && (data.result_gemini.toku || data.result_gemini.kokoro)) ? data.result_gemini : data.result,
        scoreData: { scores: data.scores, overall: data.overall, axis_comments: data.axis_comments, s_total: data.s_total },
    });
    const elyzaCard = _genModelCard({
        key: 'elyza', label: 'ELYZA', title: '🏠 純国産AI ELYZA', accent: 'border-[#5B8124]', badge: 'bg-[#5B8124]/20 text-[#5B8124]', odai: odai,
        result: data.result_llmjp,
        scoreData: { scores: data.scores_llmjp, overall: data.overall_llmjp, axis_comments: data.axis_comments_llmjp, s_total: data.s_total_llmjp },
        failed: data.llmjp_status === 'failed',
    });
    document.getElementById('gen-cards-grid').innerHTML = geminiCard + elyzaCard;
};

// 後方互換エイリアス（既存の呼び出し名を維持）
window.uiShowGenResult = window.uiRenderGenResult;
window.uiShowOmake = window.uiRenderGenResult;

// 「別のお題で作る」: 結果UIをリセットし、入力フォームへフォーカスを戻す（スクロール不要）。
window.uiResetGenerator = function() {
    const card = document.getElementById('result-card');
    if (card) card.classList.add('hidden');
    const host = document.getElementById('gen-dual');
    if (host) host.remove(); // 次回の生成でまっさらに再構築する
    const input = document.getElementById('odaiInput');
    if (input) { input.value = ''; input.focus(); input.scrollIntoView({ behavior: 'smooth', block: 'center' }); }
};

// === 生成フローのView制御（app.js の startGeneration / pollStatus から移管） ===
// Controller(app.js) は直接DOMを触らず、以下の関数を呼ぶだけにする。

// 前回の結果・エラー表示をクリアする（新しい生成の開始前）。
window.uiGenReset = function() {
    document.getElementById('result-card')?.classList.add('hidden');
    document.getElementById('error-card')?.classList.add('hidden');
    document.getElementById('gen-eval-container')?.remove();
};

// ローディング開始: 生成ボタンを無効化し、スピナーと作動中メッセージを表示する。
window.uiGenLoadingStart = function() {
    const btn = document.getElementById('generateBtn');
    if (btn) btn.disabled = true;
    document.getElementById('loading')?.classList.remove('hidden');
    const status = document.getElementById('statusMsg');
    if (status) status.innerText = "からくりが作動中...";
};

// ローディング終了: スピナーを隠し、生成ボタンを再有効化する。
window.uiGenLoadingStop = function() {
    document.getElementById('loading')?.classList.add('hidden');
    const btn = document.getElementById('generateBtn');
    if (btn) btn.disabled = false;
};

// シェア用に、生成結果カード（静的単一表示）のテキストを読み取って返すゲッター。
window.uiGetGenResultText = function() {
    const g = (id) => document.getElementById(id)?.innerText || '';
    return { odai: g('resHint'), toku: g('resToku'), kokoro: g('resKokoro'), score: g('resScore') };
};

// シェア用に、自作鑑定の結果カードのテキストを読み取って返すゲッター。
window.uiGetHumanResultText = function() {
    const g = (id) => document.getElementById(id)?.innerText || '';
    return { odai: g('hResHint'), toku: g('hResToku'), kokoro: g('hResKokoro'), score: g('hResScore') };
};

// 自作なぞかけ鑑定の結果を描画する（task例の window.uiShowResult）。
// payload = { data, odai, toku, kokoro }
window.uiShowResult = function(payload) {
    const { data, odai, toku, kokoro } = payload;
    const scores = data.scores || {};
    if(document.getElementById('hResHint')) document.getElementById('hResHint').innerText = odai; if(document.getElementById('hResToku')) document.getElementById('hResToku').innerText = toku; if(document.getElementById('hResKokoro')) document.getElementById('hResKokoro').innerText = kokoro; if(document.getElementById('hResScore')) document.getElementById('hResScore').innerText = (data.s_total || 0).toFixed(2);
    if(document.getElementById('hResReasoning')) document.getElementById('hResReasoning').innerHTML = window.uiBuildCritiqueHtml(data);
    const ctx = document.getElementById('humanRadarChart')?.getContext('2d');
    if(ctx) { const chartData = [scores.S_sur||0.5, scores.S_tech||0.5, scores.S_emo||0.5, scores.S_rhy||0.5, scores.S_sensory||0.5, scores.S_visual||0.5, scores.S_ontology||0.5, scores.S_cultural||0.5, scores.S_cm||0.5, scores.S_prosody||0.5, scores.S_nat||0.5, data.s_total?data.s_total/5:0.5]; if (window.appState.humanRadarChart) window.appState.humanRadarChart.destroy(); window.appState.humanRadarChart = new Chart(ctx, { type: 'radar', data: { labels: ['意外性', '技巧', '情緒', 'リズム', '感覚', '視覚', '存在論', '文化', '概念', '韻律', '自然さ', '総合'], datasets: [{ data: chartData, backgroundColor: 'rgba(91, 129, 36, 0.2)', borderColor: 'rgba(91, 129, 36, 1)', borderWidth: 2 }] }, options: { scales: { r: { min: 0, max: 1.0, ticks:{display:false}, pointLabels: { font: { size: 9, family: "sans-serif" } } } }, plugins: { legend: { display: false } } } }); }
    document.getElementById('human-result-card')?.classList.remove('hidden'); window.showToast("✨ 鑑定完了！");
};

// --- 生成結果のモデル別評価（Gemini / ELYZA を区別して別々に送信） ---
window._genRatings = window._genRatings || { gemini: 0, elyza: 0 };
window._genSubmitted = window._genSubmitted || { gemini: false, elyza: false };
window._genComments = window._genComments || { gemini: '', elyza: '' };

// コメント入力の保持（onclick/oninput="setGenComment('gemini', value)"）。再描画でも消えないようモデル別に保存。
window.setGenComment = function(model, value) {
    if (!window._genComments) window._genComments = { gemini: '', elyza: '' };
    window._genComments[model] = value;
};

// 星評価の選択（onclick="setGenRating('gemini', i)" 等）。モデル別に状態を保持する。
window.setGenRating = function(model, rating) {
    window._genRatings[model] = rating;
    for (let i = 1; i <= 5; i++) {
        const btn = document.getElementById(`gen-star-${model}-${i}`);
        if (!btn) continue;
        if (i <= rating) { btn.style.backgroundColor = '#C5B358'; btn.style.color = '#fff'; }
        else { btn.style.backgroundColor = '#fff'; btn.style.color = '#d1d5db'; }
    }
};

// 評価送信（onclick="submitGenEvaluation('gemini')" 等）。モデルごとに別イベントとして DB へ送る。
window.submitGenEvaluation = async function(model) {
    const score = window._genRatings[model] || 0;
    if (!score) {
        (window.showToast ? window.showToast('⚠️ 星を選択してください', 'warning') : alert('星を選択してください'));
        return;
    }
    window._genSubmitted[model] = true;
    // テキストエリアの最新値を取得（state にも保存済みだが念のため直接読む）。
    const commentEl = document.getElementById('gen-comment-' + model);
    const comment = commentEl ? commentEl.value : ((window._genComments && window._genComments[model]) || '');
    // app.js が公開する送信関数（/metrics/log にモデル別イベント＋コメントとして永続化）。失敗してもUIは進める。
    try { if (window.submitModelRating) await window.submitModelRating(model, window._genTaskId, score, comment); } catch (e) {}
    const label = model === 'gemini' ? 'Gemini' : 'ELYZA';
    const box = document.getElementById('gen-rate-' + model);
    if (box) box.innerHTML = `<div class="text-center text-[#5B8124] font-bold text-sm py-2">✨ ${label}の評価ありがとうございました</div>`;
};
