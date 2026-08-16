// frontend/ui/trivia.js
// 改修要件「コールドスタート待機演出」: サーバー起動待ち(Cloud Runコールドスタート)・
// なぞかけ生成中の体感待ち時間を、なぞかけの豆知識・過去の名作なぞかけの
// サイクル表示で緩和する。index.html(初回タイムライン取得・生成中)・
// personas.html(初回一覧取得・みんなのペルソナ取得)の両方から共通利用する。
export const NAZOKAKE_TRIVIA = [
    "なぞかけの基本形は「三段なぞ」。江戸時代から続く言葉のレトリックです。",
    "整いました!「飛行機」とかけて「お正月のおせち」と解く。その心は…どちらも「ちょうりく(着陸/重箱・鳥肉等)」が肝心です。",
    "「掛詞(かけことば)」は、ひとつの音に複数の意味を重ねる日本語ならではの言葉遊びです。",
    "なぞかけの「その心」は、一見無関係な二つのお題を結びつける発想の橋渡し役です。",
    "整いました!「時計」とかけて「相撲部屋」と解く。その心は…どちらも「まわし(針/廻し)」が命です。",
    "同音異義語を探す訓練として、なぞかけは脳のやわらかい発想力を鍛えてくれます。",
    "整いました!「桜」とかけて「有能な部下」と解く。その心は…どちらも「はな(花/鼻)」が高いです。",
    "なぞかけの起源は江戸中期の「判じ物」という謎解き遊びにさかのぼると言われています。",
    "整いました!「お相撲さん」とかけて「引っ越し当日」と解く。その心は…どちらも「なきずもう(泣き相撲/荷物)」が大変です。",
];

/**
 * containerEl のテキストを一定間隔で豆知識/名作なぞかけへ切り替える。
 * 戻り値の関数を呼ぶとタイマーを止める(ローディング終了時に必ず呼ぶこと)。
 */
export function startTriviaCarousel(containerEl, { intervalMs = 3500 } = {}) {
    if (!containerEl) return () => {};
    let i = Math.floor(Math.random() * NAZOKAKE_TRIVIA.length);
    containerEl.textContent = NAZOKAKE_TRIVIA[i];
    const timer = setInterval(() => {
        i = (i + 1) % NAZOKAKE_TRIVIA.length;
        containerEl.textContent = NAZOKAKE_TRIVIA[i];
    }, intervalMs);
    return () => clearInterval(timer);
}
