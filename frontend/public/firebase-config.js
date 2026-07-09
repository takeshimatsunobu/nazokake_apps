// frontend/public/firebase-config.js
// Firebase Web アプリの公開設定。Web の apiKey は「公開前提で安全」な識別子であり、
// サーバ用の GEMINI_API_KEY（課金キー）とは別物。クライアントに置いてよい。
//
// 以前は Firebase Hosting 専用パス /__/firebase/init.js が config を自動注入していたが、
// ローカル(FastAPI:8000)では解決できず 404 になるため、CDN compat + 明示初期化へ切り替えた。
//
// ★ apiKey: Firebase Console → プロジェクトの設定 → 全般 → マイアプリ(ウェブ) の
//   firebaseConfig.apiKey（AIza... で始まる公開Webキー）を貼ってください。
window.firebaseConfig = {
    apiKey: "AIzaSyClImunmZDLAzS93-HLGOQG6Q-8MXwnS8s",
    authDomain: "nazokakeapp-137e5.firebaseapp.com",
    projectId: "nazokakeapp-137e5",
    storageBucket: "nazokakeapp-137e5.appspot.com",
    messagingSenderId: "862686676938",
    appId: "1:862686676938:web:64489be095f5102ee6f133",
};
