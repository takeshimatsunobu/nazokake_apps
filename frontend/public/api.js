import { API_BASE } from './config.js';
import { appState } from './state.js';

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

export async function apiLogEvent(eventName, duration, tabName = "", comment = "") {
    try {
        await fetch(`${API_BASE}/metrics/log`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_slug: appState.userSlug, event_name: eventName, duration, tab_name: tabName, comment })
        });
    } catch (e) {}
}

export async function apiGenerate(odai) {
    return fetchAPI('/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ odai })
    });
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
