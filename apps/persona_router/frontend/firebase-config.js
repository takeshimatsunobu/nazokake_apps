// frontend/firebase-config.js
// Firebase Web アプリの公開設定(apps/evaluator/frontend/public/firebase-config.js と
// 同一のFirebaseプロジェクト(nazokakeapp-137e5)を指す。Web の apiKey は「公開前提で
// 安全」な識別子であり、サーバ用の GEMINI_API_KEY（課金キー）とは別物。
//
// 【persona_feature_plan_v3.md Phase7】§6でFirebase匿名認証の適用範囲をペルソナ関連
// API全般へ拡張したため(Phase6でapps/persona_router側のAPIが認証必須になった)、
// これまでFirebase Authを一切使っていなかったこのフロントエンドにも、
// evaluator/frontendと同じ構成(CDN importmap経由、npm依存の追加なし)で導入する。
export const firebaseConfig = {
    apiKey: "AIzaSyClImunmZDLAzS93-HLGOQG6Q-8MXwnS8s",
    authDomain: "nazokakeapp-137e5.firebaseapp.com",
    projectId: "nazokakeapp-137e5",
    storageBucket: "nazokakeapp-137e5.appspot.com",
    messagingSenderId: "862686676938",
    appId: "1:862686676938:web:64489be095f5102ee6f133",
    measurementId: "G-QMFX5EHEXQ",
};
