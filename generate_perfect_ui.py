import os

# 💡 バッククォートとダラー記号を独自のプレースホルダーに置き換えた安全なテンプレート
html_template = '''<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <title>なぞかけディスカバリー | AIが極める伝統話芸</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root { --primary-color: #8b0000; --bg-color: #fdfaf5; --card-bg: #ffffff; --text-main: #333333; }
        body { font-family: 'Helvetica Neue', Arial, sans-serif; background-color: var(--bg-color); color: var(--text-main); margin: 0; padding: 0; scroll-behavior: smooth; }
        header { background-color: var(--primary-color); color: white; text-align: center; padding: 20px 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); position: sticky; top: 0; z-index: 100; }
        h1 { margin: 0; font-size: 1.8rem; letter-spacing: 1px; }
        .subtitle { font-size: 0.9rem; color: #ffd700; margin-top: 5px; font-weight: bold; }
        .container { max-width: 1000px; margin: 20px auto; padding: 0 20px; }
        .post-section { background: var(--card-bg); padding: 30px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); margin-bottom: 40px; border: 3px solid var(--primary-color); transition: all 0.4s ease; }
        .post-section.highlight { box-shadow: 0 0 25px rgba(139, 0, 0, 0.6); transform: scale(1.02); border-color: #ff4500; }
        .post-section h2 { margin-top: 0; color: var(--primary-color); font-size: 1.4rem; border-bottom: 2px dashed #ccc; padding-bottom: 10px; }
        .format-row { display: flex; align-items: center; gap: 15px; margin-top: 20px; font-weight: bold; flex-wrap: nowrap; }
        .format-input { flex: 1; width: 100%; box-sizing: border-box; padding: 15px; font-size: 1.1rem; border: 1px solid #ccc; border-radius: 8px; border-bottom: 4px solid var(--primary-color); background-color: #fff9f9; font-family: inherit;}
        textarea.format-input { resize: vertical; line-height: 1.6; }
        .submit-btn { background-color: var(--primary-color); color: white; border: none; padding: 15px 20px; font-size: 1.3rem; border-radius: 8px; cursor: pointer; font-weight: bold; width: 100%; margin-top: 25px; transition: 0.3s;}
        .submit-btn:hover { background-color: #660000; transform: translateY(-2px); }
        .section-title { color: var(--primary-color); border-bottom: 3px solid var(--primary-color); padding-bottom: 5px; margin-top: 50px; font-size: 1.5rem; }
        .card { background: var(--card-bg); padding: 30px; border-radius: 12px; box-shadow: 0 4px 10px rgba(0,0,0,0.08); margin-bottom: 30px; position: relative; display: flex; flex-direction: column; }
        .card-top { display: flex; flex-direction: row; gap: 40px; justify-content: space-between; align-items: flex-start; }
        .golden-badge, .top10-badge { position: absolute; top: -15px; right: -10px; padding: 6px 20px; border-radius: 20px; font-weight: bold; font-size: 1rem; box-shadow: 0 2px 5px rgba(0,0,0,0.2); border: 2px solid #fff; z-index: 10; }
        .golden-badge { background: #ffd700; color: #333; }
        .top10-badge { background: #ff4500; color: #fff; }
        .card-content { flex: 1; min-width: 0; font-size: 1.15rem; line-height: 1.8; }
        .odai-title { font-size: 1.3rem; color: var(--primary-color); font-weight: bold; margin-bottom: 12px; word-wrap: break-word; border-bottom: 1px dotted var(--primary-color); display: inline-block; }
        .author-tag { display: inline-block; font-size: 0.85rem; background: #eee; padding: 4px 10px; border-radius: 10px; margin-bottom: 15px; color: #666; vertical-align: middle; }
        .btn-edit { background: #fff; color: var(--primary-color); border: 2px solid var(--primary-color); padding: 4px 12px; border-radius: 20px; font-size: 0.85rem; cursor: pointer; margin-left: 10px; font-weight: bold; transition: 0.2s; vertical-align: middle; display: inline-flex; align-items: center; gap: 4px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);}
        .btn-edit:hover { background: var(--primary-color); color: #fff; transform: translateY(-1px); }
        .reasoning { margin-top: 20px; font-size: 0.95rem; color: #555; background: #f9f9f9; padding: 15px; border-left: 4px solid #ccc; border-radius: 4px; overflow-wrap: break-word; }
        .chart-wrapper { width: 380px; height: 380px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; position: relative; margin-top: 10px; }
        .eval-section { width: 100%; border-top: 1px dashed #ccc; padding-top: 20px; margin-top: 25px; text-align: center; }
        .stars { display: flex; justify-content: center; gap: 10px; font-size: 2.8rem; color: #ddd; cursor: pointer; direction: rtl; }
        .stars span { transition: color 0.2s; -webkit-tap-highlight-color: transparent; }
        .stars span:hover, .stars span:hover ~ span { color: #ffd700; }
        .stars.rated span { color: #ffd700; cursor: default; }
        .eval-msg { font-size: 0.95rem; color: var(--primary-color); font-weight: bold; height: 20px; margin-top: 8px; }
        #loader { text-align: center; font-size: 1.2rem; color: var(--primary-color); margin: 50px 0; font-weight: bold; }
        @media (max-width: 768px) {
            .container { padding: 0 10px; }
            .format-row { flex-direction: column; align-items: stretch; text-align: right; gap: 8px; margin-top: 20px;}
            .format-row span { font-size: 0.95rem; color: #666; }
            .card-top { flex-direction: column; align-items: center; gap: 10px; }
            .chart-wrapper { width: 100%; max-width: 350px; height: 350px; margin: 15px auto 0; }
        }
    </style>
</head>
<body>
    <header>
        <h1>🏮 なぞかけディスカバリー</h1>
        <div class="subtitle">AIと人間が極める伝統話芸 （※ねづっち非公認）</div>
    </header>

    <div class="container">
        <div class="post-section" id="post-area">
            <h2>🔥 自分の作品を投稿する（道場破り）</h2>
            <div id="editing-badge" style="display:none; background:#ffd700; color:#333; padding:5px 15px; border-radius:20px; font-weight:bold; font-size:0.9rem; margin-bottom:15px; width:max-content;">✍️ AI作品を添削中</div>
            
            <div class="format-row"><input type="text" id="input-a" class="format-input" placeholder="例：スーパーのレジ待ち"><span>とかけて、</span></div>
            <div class="format-row"><input type="text" id="input-b" class="format-input" placeholder="例：独楽（こま）"><span>と解く。</span></div>
            <div class="format-row" style="align-items: flex-start;">
                <span style="margin-top: 15px;">その心は、</span>
                <textarea id="input-c" class="format-input" rows="3" maxlength="400" placeholder="例：どちらも『コマ（独楽／困）』でしょう。&#13;&#10;（※二段落ち、三段落ちなどの高度な技も歓迎！最大400文字）"></textarea>
            </div>
            <button class="submit-btn" id="main-submit-btn" onclick="submitHumanNazokake()">整いました！ (AIの審査へ送る)</button>
        </div>

        <div id="loader">データを読み込んでいます... 🍵</div>

        <div id="feed-container" style="display: none;">
            <h2 class="section-title">🔥 週間トップ10（Trending）</h2>
            <div id="top10-feed"></div>
            <h2 class="section-title">✨ 発掘待ち（Discovery）</h2>
            <div id="random-feed"></div>
            <h2 class="section-title">👑 殿堂入り（Golden）</h2>
            <div id="golden-feed"></div>
        </div>
    </div>

    <script>
        let currentEditingParentId = null;

        window.onload = loadFeed;

        async function loadFeed() {
            try {
                const res = await fetch('/api/feed');
                const data = await res.json();
                document.getElementById('loader').style.display = 'none';
                document.getElementById('feed-container').style.display = 'block';

                renderCards(data.top10, 'top10-feed', '🔥 ランクイン');
                renderCards(data.random, 'random-feed', '');
                renderCards(data.golden, 'golden-feed', '👑 殿堂入り');
            } catch (e) {
                console.error("Fetch Error:", e);
                document.getElementById('loader').innerText = "通信エラーが発生しました。（コンソールを確認してください）";
            }
        }

        function renderCards(items, containerId, badgeText) {
            const container = document.getElementById(containerId);
            container.innerHTML = '';
            if(!items || items.length === 0) {
                container.innerHTML = '<p style="color:#777; text-align:center; padding:20px;">現在表示できる作品がありません。</p>';
                return;
            }

            items.forEach((item, index) => {
                const card = document.createElement('div');
                card.className = 'card';
                
                let badgeHtml = '';
                if (badgeText && containerId === 'golden-feed') badgeHtml = BACKTICK<div class="golden-badge">DOLLAR{badgeText}</div>BACKTICK;
                if (badgeText && containerId === 'top10-feed') badgeHtml = BACKTICK<div class="top10-badge">🔥 第DOLLAR{index + 1}位</div>BACKTICK;

                let author = item.author || "AI Agent";
                let reasoning = item.reasoning ? BACKTICK<div class="reasoning"><strong>💡 AIの講評:</strong><br>DOLLAR{item.reasoning}</div>BACKTICK : "";
                let fullOdai = item.A_TITLE || '不明';
                let displayOdai = fullOdai.length > 20 ? fullOdai.substring(0, 20) + '...' : fullOdai;

                let safeText = item.nazokake_text.replace(/'/g, "\\\\'").replace(/"/g, '&quot;');
                let editBtnHtml = BACKTICK<button class="btn-edit" onclick="editNazokake('DOLLAR{safeText}', 'DOLLAR{item.doc_id}')">✍️ 編集して道場破り</button>BACKTICK;

                let starsHtml = BACKTICK
                    <div class="eval-section">
                        <div class="stars" id="stars-DOLLAR{item.doc_id}">
                            <span onclick="rateItem('DOLLAR{item.doc_id}', 5)">★</span>
                            <span onclick="rateItem('DOLLAR{item.doc_id}', 4)">★</span>
                            <span onclick="rateItem('DOLLAR{item.doc_id}', 3)">★</span>
                            <span onclick="rateItem('DOLLAR{item.doc_id}', 2)">★</span>
                            <span onclick="rateItem('DOLLAR{item.doc_id}', 1)">★</span>
                        </div>
                        <div class="eval-msg" id="msg-DOLLAR{item.doc_id}">この作品を評価する</div>
                    </div>
                BACKTICK;

                card.innerHTML = badgeHtml + BACKTICK
                    <div class="card-top">
                        <div class="card-content">
                            <div class="odai-title" title="DOLLAR{fullOdai}">【お題】DOLLAR{displayOdai}</div><br>
                            <span class="author-tag">✍️ 作成: DOLLAR{author}</span>DOLLAR{editBtnHtml}<br><br>
                            <strong>DOLLAR{item.nazokake_text}</strong>
                            DOLLAR{reasoning}
                        </div>
                        <div class="chart-wrapper">
                            <canvas id="chart-DOLLAR{item.doc_id}"></canvas>
                        </div>
                    </div>
                BACKTICK + starsHtml;
                container.appendChild(card);
                if(item.scores && Object.keys(item.scores).length > 0) renderRadarChart(BACKTICKchart-DOLLAR{item.doc_id}BACKTICK, item);
            });
        }

        function renderRadarChart(canvasId, item) {
            const ctx = document.getElementById(canvasId).getContext('2d');
            const scores = item.scores || {};
            let humanScoreNormalized = 0;
            if (item.user_evaluations && item.user_evaluations.length > 0) {
                const total = item.user_evaluations.reduce((sum, ev) => sum + (ev.user_score || ev.rating || 0), 0);
                humanScoreNormalized = (total / item.user_evaluations.length) / 5.0; 
            }

            new Chart(ctx, {
                type: 'radar',
                data: {
                    labels: ['人間の評価', '意外性(S_sur)', '納得感(S_emo)', '技巧性(S_tech)', 'テンポ(S_rhy)', 'ユーモア(S_humor)', '情景(S_visual)', '文化(S_cultural)', '韻律(S_prosody)', '比喩(S_cm)', '存在論(S_ontology)', '感覚(S_sensory)'],
                    datasets: [{
                        data: [humanScoreNormalized, scores.S_sur||0, scores.S_emo||0, scores.S_tech||0, scores.S_rhy||0, scores.S_humor||0, scores.S_visual||0, scores.S_cultural||0, scores.S_prosody||0, scores.S_cm||0, scores.S_ontology||0, scores.S_sensory||0],
                        backgroundColor: 'rgba(139, 0, 0, 0.15)', borderColor: 'rgba(139, 0, 0, 0.8)',
                        pointBackgroundColor: function(context) { return context.dataIndex === 0 ? '#ffd700' : '#8b0000'; },
                        pointBorderColor: '#fff', pointRadius: 4, borderWidth: 2
                    }]
                },
                options: {
                    responsive: true, maintainAspectRatio: false, layout: { padding: 10 },
                    scales: { r: { angleLines: { display: true, color: 'rgba(0,0,0,0.1)' }, grid: { color: 'rgba(0,0,0,0.1)' }, suggestedMin: 0, suggestedMax: 1.0, ticks: { display: false }, pointLabels: { font: { size: 11, family: 'Meiryo' }, color: function(context) { return context.index === 0 ? '#ff4500' : '#666'; } } } },
                    plugins: { legend: { display: false } }
                }
            });
        }

        function editNazokake(fullText, docId) {
            document.getElementById('input-a').value = '';
            document.getElementById('input-b').value = '';
            document.getElementById('input-c').value = '';
            currentEditingParentId = docId;
            
            document.getElementById('editing-badge').style.display = 'block';
            document.getElementById('main-submit-btn').innerText = "整えました！ (AI作品を添削して道場破り)";

            const match = fullText.match(/(?:「|『)?([^」』]+?)(?:」|』)?\s*とかけて.*?(?:「|『)?([^」』]+?)(?:」|』)?\s*と解く。.*?その心は[、\s]*(.*)DOLLAR/is);

            if(match && match.length === 4) {
                document.getElementById('input-a').value = match[1].trim();
                document.getElementById('input-b').value = match[2].trim();
                document.getElementById('input-c').value = match[3].trim();
            } else {
                alert("AIの表現が特殊なため、自動で分解できませんでした。テキストボックス内で手動で整えてください！");
                document.getElementById('input-c').value = fullText;
            }

            window.scrollTo({ top: 0, behavior: 'smooth' });
            const postArea = document.getElementById('post-area');
            postArea.classList.add('highlight');
            setTimeout(() => { postArea.classList.remove('highlight'); }, 1500);
        }

        async function rateItem(docId, score) {
            const starsContainer = document.getElementById(BACKTICKstars-DOLLAR{docId}BACKTICK);
            const msgBox = document.getElementById(BACKTICKmsg-DOLLAR{docId}BACKTICK);
            if (starsContainer.classList.contains('rated')) return;
            try {
                const res = await fetch('/api/evaluate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ doc_id: docId, user_score: score }) });
                if(res.ok) {
                    starsContainer.classList.add('rated');
                    starsContainer.querySelectorAll('span').forEach((star, i) => { star.style.color = (5 - i <= score) ? '#ffd700' : '#ddd'; });
                    msgBox.innerText = BACKTICK★DOLLAR{score} で評価しました！BACKTICK; msgBox.style.color = '#ff4500';
                } else { msgBox.innerText = 'エラーが発生しました。'; }
            } catch(e) { msgBox.innerText = '通信エラーです。'; }
        }

        async function submitHumanNazokake() {
            const a = document.getElementById('input-a').value.trim();
            const b = document.getElementById('input-b').value.trim();
            const c = document.getElementById('input-c').value.trim();

            if(!a || !b || !c) { alert('おっと！空欄がありますよ。しっかり整えてください！'); return; }

            const fullText = BACKTICK「DOLLAR{a}」とかけて、「DOLLAR{b}」と解く。その心は、DOLLAR{c}BACKTICK;
            const submitBtn = document.getElementById('main-submit-btn');
            submitBtn.innerText = "審査中...（AIが採点しています）";
            submitBtn.disabled = true;

            try {
                const response = await fetch('/api/submit_human', { 
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ 
                        odai: a, 
                        nazokake_text: fullText, 
                        parent_id: currentEditingParentId 
                    })
                });

                if(response.ok) {
                    alert('投稿完了！あなたの作品がAIによって審査・登録されました！');
                    document.getElementById('input-a').value = '';
                    document.getElementById('input-b').value = '';
                    document.getElementById('input-c').value = '';
                    currentEditingParentId = null;
                    document.getElementById('editing-badge').style.display = 'none';
                    loadFeed();
                } else { alert('エラーが発生しました。'); }
            } catch (e) { alert('通信エラーです。'); } 
            finally {
                submitBtn.innerText = "整いました！ (AIの審査へ送る)";
                submitBtn.disabled = false;
            }
        }
    </script>
</body>
</html>'''

# 💡 安全な置換によって、消滅していた記号たちを復元します
final_html = html_template.replace('BACKTICK', chr(96)).replace('DOLLAR', chr(36))

with open('frontend/index.html', 'w', encoding='utf-8') as f:
    f.write(final_html)

print("✅ frontend/index.html を安全に生成し、復旧させました！")
