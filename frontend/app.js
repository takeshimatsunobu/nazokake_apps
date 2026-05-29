// 💡 1. AI生成の実行と段階的レンダリング（究極UX完全版）
document.getElementById('btn-generate').addEventListener('click', async () => {
    const odai = document.getElementById('gen-odai-input').value.trim();
    if (!odai) return alert('お題を入力してください');
    
    const loader = document.getElementById('loading-overlay');
    const loadingText = document.getElementById('loading-text');
    const inputSection = document.getElementById('gen-input-section');
    const resultAreaId = 'gen-result-area';

    inputSection.classList.add('hidden');
    loadingText.innerText = 'AIがなぞかけを考案中...';
    loader.classList.remove('hidden');

    try {
        // フェーズ1: テキスト生成APIだけを叩く (約3〜5秒で完了！)
        const genRes = await fetch(URL_GENERATE, { 
            method: 'POST', 
            headers: {'Content-Type': 'application/json'}, 
            body: JSON.stringify({ odai: odai }) 
        });
        
        if (!genRes.ok) throw new Error("生成サーバーエラー");
        
        const genData = await genRes.json();
        const generatedText = genData.nazokake || genData.nazokake_text;
        
        if (!generatedText) throw new Error("テキストが生成されませんでした。");

        // 【大成功！】ここで無駄な全体グルグルを強制解除し、なぞかけ本文をドーンと表示！
        loader.classList.add('hidden');
        const area = document.getElementById(resultAreaId);
        area.innerHTML = `
            <div class="riddle-full-view shadow-card">
                <div class="tag">整いました！</div>
                <p class="output-text riddle-text-large">${generatedText.replace(/\*\*/g, "")}</p>
            </div>
            <div id="eval-spinner" style="text-align:center; padding: 20px; color: var(--gold); border: 1px dashed var(--gold); margin-top: 15px; border-radius: 8px;">
                <div style="font-size: 24px; animation: spin 2s linear infinite;">⏳</div>
                <p style="margin-top: 10px; font-weight: bold;">【審査中】最高峰AI審査員がこの作品を多角的に鑑定しています...</p>
                <p style="font-size: 0.8em; opacity: 0.8;">※なぞかけを味わいながら少々お待ちください</p>
            </div>
        `;
        
        // CSSスピンアニメーションの注入
        if(!document.getElementById('spin-style')) {
            const style = document.createElement('style');
            style.id = 'spin-style';
            style.innerHTML = `@keyframes spin { 100% { transform: rotate(360deg); } }`;
            document.head.appendChild(style);
        }

        // フェーズ2: Firestoreに保存して評価プロセスをトリガーする
        const payload = {
            A_TITLE: odai,
            B_TITLE: "AI_GENERATED",
            C_READING: "AI_GENERATED",
            A_CONTEXT_DETAIL: "AIによる自動生成",
            GENERATION_TYPE: "AI",
            nazokake_text: generatedText
        };
        const submitRes = await fetch(URL_SUBMIT_HUMAN, { 
            method: 'POST', 
            headers: {'Content-Type': 'application/json'}, 
            body: JSON.stringify(payload) 
        });
        const submitData = await submitRes.json();

        // フェーズ3: Firestoreを監視し、評価が完了したらレーダーチャートを描画
        const unsub = onSnapshot(doc(db, COLLECTION_NAME, submitData.doc_id), (docSnap) => {
            if (docSnap.exists()) {
                const resultData = docSnap.data();
                resultData.doc_id = docSnap.id;
                
                if (resultData.status === -1 || resultData.eval_status === "error") {
                    document.getElementById('eval-spinner').innerHTML = `<p style="color:red; font-weight:bold;">⚠️ 評価プロセスでエラーが発生しました</p>`;
                    unsub(); 
                    return;
                }
                
                const hasScores = resultData.scores && Object.keys(resultData.scores).length > 0;
                if (hasScores) {
                    // 評価完了！ミニスピンを消して完全版（レーダーチャート等）を描画
                    renderResult(resultAreaId, 'gen-input-section', resultData);
                    unsub(); // 監視終了
                }
            }
        });

    } catch (e) {
        console.error("生成エラー:", e);
        alert("🚨 処理中にエラーが発生しました:\n" + e.message);
        loader.classList.add('hidden');
        inputSection.classList.remove('hidden');
    }
});