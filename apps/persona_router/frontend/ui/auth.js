// frontend/ui/auth.js
// Firebase匿名認証(apps/evaluator/frontend/public/ui/auth.js と同じパターン)。
//
// 【persona_feature_plan_v3.md Phase6/Phase7】マイペルソナAPI(/v1/personas系)は
// Firebase IDトークンによる認証を必須とするため(apps/persona_router/api/deps.py::
// verify_user_token)、このフロントエンドでも匿名サインインを行い、APIリクエストの
// Authorizationヘッダーへ都度トークンを載せる(api.js::authHeader参照)。
//
// 【state.jsのuidとは別物】state.jsのappState.uidは/v1/generate用のローカル生成
// UUID(client_uuid、サーバー未検証)であり、ここで得るFirebase UIDとは異なる概念。
// マイペルソナのowner_uidには必ずこちらのFirebase UIDを使う。
// @ts-nocheck -- 未移行(Firebase CDN importのため)
import { initializeApp } from "firebase/app";
import { getAuth, signInAnonymously, onAuthStateChanged } from "firebase/auth";
import { firebaseConfig } from "firebase-config";

const app = initializeApp(firebaseConfig);
export const auth = getAuth(app);

export let currentUid = null;
let readyPromise = null;

export function ensureAnonAuth() {
    if (readyPromise) return readyPromise;
    readyPromise = new Promise((resolve, reject) => {
        onAuthStateChanged(auth, async (user) => {
            if (user) {
                currentUid = user.uid;
                const idToken = await user.getIdToken();
                resolve(idToken);
            } else {
                signInAnonymously(auth).catch((error) => {
                    console.error("🔥 [Error] 匿名ログイン失敗:", error.code, error.message);
                    reject(error);
                });
            }
        });
    });
    return readyPromise;
}

// APIリクエスト直前に呼ぶ。IDトークンは有効期限(既定1時間)があるため、都度
// getIdToken()を呼んで自動更新に任せる(firebase/authが内部でキャッシュ・更新する。
// forceRefreshは指定しないため、通常は追加のネットワーク往復は発生しない)。
export async function getFreshIdToken() {
    await ensureAnonAuth();
    if (!auth.currentUser) throw new Error("認証状態を確立できませんでした。");
    return auth.currentUser.getIdToken();
}
