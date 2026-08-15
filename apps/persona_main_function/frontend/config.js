// frontend/config.js
// API_BASEは全フロントエンドJSにとっての唯一のSSoT(apps/evaluator/frontend/public/config.js
// と同じ理由・同じ形。過去に複製して食い違いを起こした教訓があるため、値を複製せず
// この1箇所だけをimportして使うこと)。
//
// 【本番側を絶対URLではなく相対パスにしている理由(確定済み・デプロイ準備で決定)】
// apps/evaluator/frontend/public/config.js が過去に踏んだ教訓と同じ理由で、
// Cloud RunのURLをここへハードコードしない。apps/persona_main_function/firebase.json の
// hosting.rewrites で "/v1/**" と "/healthz" をCloud Runサービス
// (nazokake-persona-router, asia-northeast1)へ直接プロキシするよう設定したため、
// 相対パス("") だけで以下の両方が同一オリジン(=CORS不要)として動作する:
//   - Firebase Hosting経由(https://nazokake-persona-router.web.app 等)でアクセスした場合
//   - 将来Cloud Runのサービス名やリージョンが変わっても、直すのは firebase.json 側の
//     1箇所だけで済む(このファイルはCloud RunのURLを一切知らなくてよい)
// ローカル開発時のみ、main.pyのCORSMiddleware許可済みのURL(http://127.0.0.1:8080)へ
// 直接クロスオリジンで通信する。
export const API_BASE =
    (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1")
        ? "http://127.0.0.1:8080"
        : "";
