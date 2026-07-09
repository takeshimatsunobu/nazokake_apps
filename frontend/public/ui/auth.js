import { initializeApp } from "https://www.gstatic.com/firebasejs/10.8.0/firebase-app.js";
import { getAuth, signInAnonymously, onAuthStateChanged } from "https://www.gstatic.com/firebasejs/10.8.0/firebase-auth.js";

const firebaseConfig = {
    apiKey: "AIzaSyClImunmZDLAzS93-HLGOQG6Q-8MXwnS8s",
    authDomain: "nazokakeapp-137e5.firebaseapp.com",
    projectId: "nazokakeapp-137e5",
    storageBucket: "nazokakeapp-137e5.firebasestorage.app",
    messagingSenderId: "862686676938",
    appId: "1:862686676938:web:64489be095f5102ee6f133",
    measurementId: "G-QMFX5EHEXQ"
};

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
