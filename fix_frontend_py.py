import os

def fix_frontend():
    file_path = 'frontend/index.html'
    if not os.path.exists(file_path):
        print("⚠️ index.html が見つかりません。")
        return

    with open(file_path, 'r', encoding='utf-8') as f:
        html = f.read()

    last_script_idx = html.rfind('<script>')
    if last_script_idx == -1:
        print("⚠️ <script>タグが見つかりません。")
        return

    before_script = html[:last_script_idx]

    # r''' ''' を使うことで、中の文字を一切エスケープせず、そのまま書き込みます
    new_script = r'''<script>
    // 💡 裏側で「どの作品を編集中か」を保持するグローバル変数
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
            console.error(e);
            document.getElementById('loader').innerText = "通信エラーが発生しました。";
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
            if (badgeText && containerId === 'golden-feed') badgeHtml = <div class="golden-badge"></div>;
            if (badgeText && containerId === 'top10-feed') badgeHtml = <div class="top10-badge">🔥 第位</div>;

            let author = item.author || "AI Agent";
            let reasoning = item.reasoning ? <div class="reasoning"><strong>💡 AIの講評:</strong><br></div> : "";
            let fullOdai = item.A_TITLE || '不明';
            let displayOdai = fullOdai.length > 20 ? fullOdai.substring(0, 20) + '...' : fullOdai;

            let safeText = item.nazokake_text.replace(/'/g, "\\'").replace(/"/g, '&quot;');
            let editBtnHtml = <button class="btn-edit" onclick="editNazokake('', '')">✍️ 編集して道場破り</button>;

            let starsHtml = 
                <div class="eval-section">
                    <div class="stars" id="stars-">
                        <span onclick="rateItem('', 5)">★</span>
                        <span onclick="rateItem('', 4)">★</span>
                        <span onclick="rateItem('', 3)">★</span>
                        <span onclick="rateItem('', 2)">★</span>
                        <span onclick="rateItem('', 1)">★</span>
                    </div>
                    <div class="eval-msg" id="msg-">この作品を評価する</div>
                </div>
            ;

            card.innerHTML = badgeHtml + 
                <div class="card-top">
                    <div class="card-content">
                        <div class="odai-title" title="">【お題】</div><br>
                        <span class="author-tag">✍️ 作成: </span><br><br>
                        <strong></strong>
                        
                    </div>
                    <div class="chart-wrapper">
                        <canvas id="chart-"></canvas>
                    </div>
                </div>
             + starsHtml;
            container.appendChild(card);
            if(item.scores && Object.keys(item.scores).length > 0) renderRadarChart(chart-, item);
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

        const match = fullText.match(/(?:「|『)?([^」』]+?)(?:」|』)?\s*とかけて.*?(?:「|『)?([^」』]+?)(?:」|』)?\s*と解く。.*?その心は[、\s]*(.*)$/is);

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
        const starsContainer = document.getElementById(stars- + docId);
        const msgBox = document.getElementById(msg- + docId);
        if (starsContainer.classList.contains('rated')) return;
        try {
            const res = await fetch('/api/evaluate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ doc_id: docId, user_score: score }) });
            if(res.ok) {
                starsContainer.classList.add('rated');
                starsContainer.querySelectorAll('span').forEach((star, i) => { star.style.color = (5 - i <= score) ? '#ffd700' : '#ddd'; });
                msgBox.innerText = ★ で評価しました！; msgBox.style.color = '#ff4500';
            } else { msgBox.innerText = 'エラーが発生しました。'; }
        } catch(e) { msgBox.innerText = '通信エラーです。'; }
    }

    async function submitHumanNazokake() {
        const a = document.getElementById('input-a').value.trim();
        const b = document.getElementById('input-b').value.trim();
        const c = document.getElementById('input-c').value.trim();

        if(!a || !b || !c) { alert('おっと！空欄がありますよ。しっかり整えてください！'); return; }

        const fullText = 「」とかけて、「」と解く。その心は、;
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

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(before_script + new_script)
    print("✅ 成功: frontend/index.html を完全に復旧しました！(バグなし・文字化けなし)")

if __name__ == '__main__':
    fix_frontend()
