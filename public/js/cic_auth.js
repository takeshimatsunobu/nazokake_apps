console.log("[CIC] Auth boot");

// instructions/236: apps/evaluator/frontend/public/admin.js と同じFirebase Web設定
// (公開前提で安全な識別子、apps/evaluator/frontend/public/firebase-config.js参照)。
// /cicは別のStaticFilesマウント(リポジトリ直下public/)のため、そちらのESM
// importmapを共有できず、ここではcompat SDK向けにオブジェクトを直接複製する。
var CIC_FIREBASE_CONFIG = {
    apiKey: "AIzaSyClImunmZDLAzS93-HLGOQG6Q-8MXwnS8s",
    authDomain: "nazokakeapp-137e5.firebaseapp.com",
    projectId: "nazokakeapp-137e5",
    storageBucket: "nazokakeapp-137e5.appspot.com",
    messagingSenderId: "862686676938",
    appId: "1:862686676938:web:64489be095f5102ee6f133",
    measurementId: "G-QMFX5EHEXQ",
};

if (typeof firebase !== 'undefined' && !firebase.apps.length) {
    firebase.initializeApp(CIC_FIREBASE_CONFIG);
}

var cicAuthUi = new firebaseui.auth.AuthUI(firebase.auth());
var cicAuthUiConfig = {
    callbacks: {
        signInSuccessWithAuthResult: function () {
            return false; // リダイレクトさせない(admin.jsと同じ)
        },
    },
    signInFlow: 'popup',
    signInOptions: [firebase.auth.GoogleAuthProvider.PROVIDER_ID],
};

firebase.auth().onAuthStateChanged(function (user) {
    var loginScreen = document.getElementById('cic-login-screen');
    var mainScreen = document.getElementById('cic-main-screen');
    if (user) {
        if (loginScreen) loginScreen.style.display = 'none';
        if (mainScreen) mainScreen.style.display = '';
    } else {
        if (loginScreen) loginScreen.style.display = 'flex';
        if (mainScreen) mainScreen.style.display = 'none';
        cicAuthUi.start('#cic-firebaseui-auth-container', cicAuthUiConfig);
    }
});

// api/deps.pyのverify_admin_tokenが要求するBearerトークンを付与するfetchラッパー。
// cic_app.js側は素のfetch()の代わりにこれを使う(admin.jsのauthFetchと同じ役割)。
window.cicAuthFetch = function (url, options) {
    options = options || {};
    var user = firebase.auth().currentUser;
    if (!user) {
        return Promise.reject(new Error("ログインしていません"));
    }
    return user.getIdToken().then(function (token) {
        var headers = Object.assign(
            { 'Content-Type': 'application/json' },
            options.headers || {},
            { 'Authorization': 'Bearer ' + token }
        );
        return fetch(url, Object.assign({}, options, { headers: headers }));
    });
};
