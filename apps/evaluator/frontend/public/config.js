// API_BASEは全フロントエンドJSにとっての唯一のSSoT。admin.js/main_index.js はこの定数を
// importして使い、値を複製しない(過去に複製して7800/8000の食い違いでERR_CONNECTION_REFUSEDを
// 起こした教訓)。
//
// 【本番側を絶対URLから相対パスへ変更した理由】Cloud Runのサービス名がnazokake-backend→
// nazokake-apiへ変わっただけでCORSエラーが発生した(URLをハードコードする限り、サービス名や
// リージョンが変わるたびにここを書き換え続ける必要があり、更新漏れが構造的に再発する)。
// apps/evaluator/firebase.json の hosting.rewrites で "/api/**" をCloud Runサービスへ
// 直接プロキシするよう設定したため、"/api"という相対パスだけで以下の両方が同一オリジン
// (=CORS不要)として動作する:
//   - Firebase Hosting経由(https://nazokakeapp-137e5.web.app)でアクセスした場合
//   - Cloud RunのURLへ直接アクセスした場合(バックエンド自身がStaticFilesでフロントエンドも
//     配信しているため、/apiも同じオリジン)
// Cloud Runのサービス名が今後また変わっても、firebase.json側の1箇所を直すだけで済む。
export const API_BASE = (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') ? 'http://127.0.0.1:8000/api' : '/api';
export const APP_URL = "https://nazokakeapp-137e5.web.app/";
