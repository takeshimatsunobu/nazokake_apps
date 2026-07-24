// @ts-nocheck -- 未移行(段階的にJSDoc型付けを進める対象。Firebase CDN importのため)
import { initializeApp } from "firebase/app";
import { getAuth, signInAnonymously, onAuthStateChanged } from "firebase/auth";
import { firebaseConfig } from "firebase-config";

const app = initializeApp(firebaseConfig);
export const auth = getAuth(app);

export let currentUid = null;

export async function ensureAnonAuth() {
    return new Promise((resolve, reject) => {
        onAuthStateChanged(auth, async (user) => {
            if (user) {
                currentUid = user.uid;
                const idToken = await user.getIdToken();
                console.log("🔒 [Security] Firebase Anonymous Auth 成功. UID:", currentUid);
                resolve(idToken);
            } else {
                signInAnonymously(auth).catch((error) => {
                    console.error("🔥 [Error] 匿名ログイン失敗:", error.code, error.message);
                    reject(error);
                });
            }
        });
    });
}
