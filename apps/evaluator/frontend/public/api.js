import { API_BASE, V1_API_BASE } from 'config';
import { appState } from 'state';

// 共通のフェッチラッパー
async function fetchAPI(endpoint, options = {}) {
    const response = await fetch(`${API_BASE}${endpoint}`, options);
    if (!response.ok) {
        let errorMessage = "通信エラー";
        try {
            const errorData = await response.json();
            errorMessage = errorData.detail || errorData.message || errorMessage;
        } catch (e) {}
        throw new Error(errorMessage);
    }
    return response.json();
}

// 【2026-08-16改修: メイン画面のマイペルソナ/みんなのペルソナ対応】/v1/**系は
// API_BASE(/apiプレフィックス付き)とは別のベースURL(V1_API_BASE、config.js参照)
// を使う専用ラッパー。
async function fetchV1API(endpoint, options = {}) {
    const response = await fetch(`${V1_API_BASE}${endpoint}`, options);
    if (!response.ok) {
        let errorMessage = "通信エラー";
        try {
            const errorData = await response.json();
            errorMessage = errorData.detail || errorData.message || errorMessage;
        } catch (e) {}
        throw new Error(errorMessage);
    }
    return response.json();
}

export async function apiLogEvent(eventName, duration, tabName = "", comment = "") {
    try {
        await fetch(`${API_BASE}/metrics/log`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_slug: appState.userSlug, event_name: eventName, duration, tab_name: tabName, comment })
        });
    } catch (e) {}
}

export async function apiGenerate(odai, personaId = 1, temperature = 0.6) {
    return fetchAPI('/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ odai, persona_id: personaId, temperature })
    });
}

// 【2026-08-16改修: メイン画面のマイペルソナ/みんなのペルソナ対応】
// GET /v1/personas はFirebase IDトークンによる認証が必須(組み込み+自分の
// マイペルソナのみを返す)。呼び出し元(app.js)がensureAnonAuth()/
// auth.currentUser.getIdToken()で取得したトークンをそのまま渡す。
export async function apiFetchPersonas(idToken) {
    const data = await fetchV1API('/v1/personas', {
        headers: { 'Authorization': `Bearer ${idToken}` },
    });
    return data.personas;
}

// GET /v1/personas/popular は認証不要の公開ランキングAPI。
export async function apiFetchPopularPersonas(limit = 10) {
    const data = await fetchV1API(`/v1/personas/popular?limit=${limit}`);
    return data.personas;
}

export async function apiGetStatus(taskId) {
    return fetchAPI(`/status/${taskId}`);
}

export async function apiSubmitHumanRiddle(odai, nazokakeText) {
    return fetchAPI('/submit_human', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ odai, nazokake_text: nazokakeText, parent_id: null })
    });
}

/**
 * @param {string | null} [lastDocId]
 * @param {number} [limit]
 * @returns {Promise<import('../api').components['schemas']['FeedItemsResponse']>}
 */
export async function apiFetchFeed(lastDocId = null, limit = 5) {
    const queryParams = lastDocId ? `?last_doc_id=${lastDocId}&limit=${limit}` : `?limit=${limit}`;
    return fetchAPI(`/feed/items${queryParams}`);
}

export async function apiSubmitFeedEvaluation(docId, evalData) {
    return fetchAPI(`/feed/evaluate/${docId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...evalData, user_slug: appState.userSlug })
    });
}

export async function apiSubmitFeedback(score, comment) {
    return fetchAPI('/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ score, comment, user_slug: appState.userSlug })
    });
}

export async function apiFetchBoard(category = 'nazokake') {
    return fetchAPI(`/board/items?category=${category}`);
}

export async function apiPostBoard(body, parentId, idToken, category = 'nazokake') {
    return fetchAPI('/board/post', {
        method: 'POST',
        headers: { 
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${idToken}`
        },
        body: JSON.stringify({ body, parent_id: parentId, category })
    });
}
