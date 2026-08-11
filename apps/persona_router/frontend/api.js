// frontend/api.js
// バックエンド(apps/persona_router)への薄いfetchラッパー群
// (apps/evaluator/frontend/public/api.js と同じ fetchAPI パターンを踏襲)。
import { API_BASE } from "config";

async function fetchAPI(path, options = {}) {
    const res = await fetch(`${API_BASE}${path}`, options);
    if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try {
            const body = await res.json();
            detail = body.detail || body.message || detail;
        } catch (e) {
            // レスポンスボディがJSONでない場合はHTTPステータスのみで諦める。
        }
        throw new Error(detail);
    }
    return res.json();
}

export async function apiFetchPersonas() {
    const data = await fetchAPI("/v1/personas");
    return data.personas;
}

export async function apiGenerate(odai, personaId, clientUuid) {
    return fetchAPI("/v1/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ odai, persona_id: personaId, client_uuid: clientUuid }),
    });
}

// 段階的ブロック: ブロック画面の「運営へ直談判する」フォーム送信。
export async function apiSubmitUnlockRequest(clientUuid, message) {
    return fetchAPI("/v1/unlock-requests", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ client_uuid: clientUuid, message }),
    });
}

// Phase3: 「赤ペン」添削の送信。
export async function apiSubmitCorrection({ originalDocId, clientUuid, penName, correctedToku, correctedKokoro }) {
    return fetchAPI("/v1/corrections", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            original_doc_id: originalDocId,
            client_uuid: clientUuid,
            pen_name: penName,
            corrected_toku: correctedToku,
            corrected_kokoro: correctedKokoro,
        }),
    });
}

export async function apiFetchTimeline({ before = null, limit = 20 } = {}) {
    const params = new URLSearchParams({ limit: String(limit) });
    if (before) params.set("before", before);
    return fetchAPI(`/v1/timeline?${params.toString()}`);
}

export async function apiZabuton(docId) {
    return fetchAPI(`/v1/timeline/${encodeURIComponent(docId)}/zabuton`, {
        method: "POST",
    });
}
