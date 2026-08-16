// frontend/config.js
// API_BASEは全フロントエンドJSにとっての唯一のSSoT(apps/evaluator/frontend/public/config.js
// と同じ理由・同じ形。過去に複製して食い違いを起こした教訓があるため、値を複製せず
// この1箇所だけをimportして使うこと)。
//
// 【2026-08-16: 統合モノリス化(案B)に伴う変更】/v1/personas・/v1/generate等のバックエンド
// ロジックはapps/evaluator/backendへ統合され、このアプリ独自のCloud Runサービス
// (旧nazokake-persona-router)は使われなくなった。ローカル開発時は統合先の
// evaluator/backend(run_api.ps1の既定ポート8000、apps/evaluator/frontend/public/
// config.jsと同じポート)へ向ける。evaluator側は/apiプレフィックス無しで/v1/*・/healthz
// を直接公開しているため、パスの末尾に/apiは付けない。
//
// 【本番側を絶対URLではなく相対パスにしている理由は維持】apps/persona_main_function/
// firebase.json の hosting.rewrites を、統合先のCloud Runサービス(nazokake-api)へ
// 向け直した(このファイル自身はCloud RunのURLを一切知らなくてよい設計を維持)。
export const API_BASE =
    (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1")
        ? "http://127.0.0.1:8000"
        : "";
