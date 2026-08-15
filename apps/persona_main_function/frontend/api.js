// frontend/api.js
// バックエンド(apps/persona_main_function)への薄いfetchラッパー群
// (apps/evaluator/frontend/public/api.js と同じ fetchAPI パターンを踏襲)。
import { API_BASE } from "config";
import { getFreshIdToken } from "ui/auth";

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

// 【persona_feature_plan_v3.md Phase6/Phase7】マイペルソナAPI(/v1/personas系、
// GET /v1/personas/schema を除く)はFirebase IDトークンによる認証を必須とする。
// 呼び出し直前に毎回フレッシュなトークンを取得してAuthorizationヘッダーへ載せる。
async function fetchAuthedAPI(path, options = {}) {
    const idToken = await getFreshIdToken();
    return fetchAPI(path, {
        ...options,
        headers: { ...(options.headers || {}), Authorization: `Bearer ${idToken}` },
    });
}

// 【Phase6でGET /v1/personasが認証必須+レスポンス形状変更(persona_id:number,name
// → persona_id:string,display_name 他多数のフィールド)になったことに伴う変更】
// 生成用のペルソナチップ(app.js)・マイペルソナ管理(ui/personas.js)の両方から
// 呼ばれる共通の取得口。
export async function apiFetchPersonas() {
    const data = await fetchAuthedAPI("/v1/personas");
    return data.personas;
}

// ------------------------------------------------------------
// persona_feature_plan_v3.md Phase6 §7.1: マイペルソナAPI(新規追加分)。
// ------------------------------------------------------------

export async function apiFetchPersonaSchema() {
    // GET /v1/personas/schema は認証不要(静的な参照データ、api/routers/personas.py参照)。
    const data = await fetchAPI("/v1/personas/schema");
    return data.fields;
}

export async function apiDraftPersona(displayName) {
    return fetchAuthedAPI("/v1/personas/draft", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ display_name: displayName }),
    });
}

export async function apiCreatePersona(settings, basePersonaId = null) {
    return fetchAuthedAPI("/v1/personas", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ settings, base_persona_id: basePersonaId }),
    });
}

export async function apiUpdatePersona(personaId, settings) {
    return fetchAuthedAPI(`/v1/personas/${encodeURIComponent(personaId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ settings }),
    });
}

export async function apiDeletePersona(personaId) {
    return fetchAuthedAPI(`/v1/personas/${encodeURIComponent(personaId)}`, {
        method: "DELETE",
    });
}

export async function apiReorderPersonas(orderedPersonaIds) {
    return fetchAuthedAPI("/v1/personas/order", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ordered_persona_ids: orderedPersonaIds }),
    });
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

// 【persona_feature_plan_v3.md Phase9クリーンアップ】「赤ペン」添削の送信先が
// POST /v1/corrections(このアプリ独自のFirestore corrections系統)からevaluator
// backend側のPOST /feed/evaluate/{doc_id}(SQLite user_akapen系統)へ一本化された
// ため、この関数と対応するUI(index.htmlの赤ペンモーダル、app.jsのopenRedpenModal等)
// を削除した。旧実装はgit履歴を参照。

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
