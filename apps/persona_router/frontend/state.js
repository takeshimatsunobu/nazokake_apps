// frontend/state.js
// 匿名UUID管理と、クライアント側だけで完結する「自分の生成物」「座布団済み」の記録。
//
// 【ファクトチェックの結論】バックエンド(models/schemas.py::GenerateRoutedRequest)は
// extra="forbid"でuser_id等の余剰フィールドを一切受け付けないため、匿名UUIDを
// /v1/generateへ送る必要はない。/v1/generateのレスポンスに含まれるdoc_idをこの
// UUIDに紐づけてlocalStorageだけで管理すれば、既存スキーマを一切変更せずに
// 「自分の作品」を識別できる(Phase3の赤ペン送信でペンネームと共にサーバー側の
// 概念が必要になった時点で、その専用スキーマを新設すればよい)。

const STORAGE_KEYS = {
    uid: "nazopr_uid",
    myDocs: "nazopr_my_docs",
    zabutonReacted: "nazopr_zabuton_reacted",
    // 【段階的ブロック機能で追加】直近に判明したブロック解除予定時刻をキャッシュする。
    // /v1/generateはユーザーが実際に生成を試みた時にしかブロック状態を教えてくれない
    // (専用のステータス確認APIは追加していない、要件のシンプルさ優先)ため、一度
    // BLOCKEDが判明したらここに保存し、次回訪問時にリロード一発でブロック画面を
    // 復元できるようにする(サーバーへ問い合わせずに済む)。
    blockedUntil: "nazopr_blocked_until",
};

// 記録の無限肥大化を防ぐ上限(古いものから捨てる)。
const MAX_TRACKED_DOCS = 300;

function readJsonArray(key) {
    try {
        const raw = localStorage.getItem(key);
        const parsed = raw ? JSON.parse(raw) : [];
        return Array.isArray(parsed) ? parsed : [];
    } catch (e) {
        return [];
    }
}

function pushBounded(key, value) {
    const list = readJsonArray(key);
    if (list.includes(value)) return;
    list.push(value);
    while (list.length > MAX_TRACKED_DOCS) list.shift();
    localStorage.setItem(key, JSON.stringify(list));
}

function ensureUid() {
    let uid = localStorage.getItem(STORAGE_KEYS.uid);
    if (!uid) {
        uid = (typeof crypto !== "undefined" && crypto.randomUUID)
            ? crypto.randomUUID()
            : `anon-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
        localStorage.setItem(STORAGE_KEYS.uid, uid);
    }
    return uid;
}

export const appState = {
    uid: ensureUid(),
    selectedPersonaId: 1,
    // 【Phase6でGET /v1/personasの形状変更】persona_idは文字列(組み込みは"1"〜"10"、
    // カスタムはUUID)、表示名はdisplay_name。is_builtinで組み込み/カスタムを判別する。
    personas: /** @type {{persona_id:string, display_name:string, is_builtin:boolean}[]} */ ([]),
    // 直近の再描画済みタイムライン先頭のcreated_at(新着ポーリングの基準点)。
    newestSeenCreatedAt: /** @type {string|null} */ (null),
};

export function markAsMine(docId) {
    pushBounded(STORAGE_KEYS.myDocs, docId);
}

export function isMine(docId) {
    return readJsonArray(STORAGE_KEYS.myDocs).includes(docId);
}

export function hasReactedZabuton(docId) {
    return readJsonArray(STORAGE_KEYS.zabutonReacted).includes(docId);
}

export function markZabutonReacted(docId) {
    pushBounded(STORAGE_KEYS.zabutonReacted, docId);
}

// ------------------------------------------------------------
// 段階的ブロック: ブロック解除予定時刻のキャッシュ
// ------------------------------------------------------------

export function getCachedBlockedUntil() {
    return localStorage.getItem(STORAGE_KEYS.blockedUntil);
}

export function setCachedBlockedUntil(isoString) {
    if (isoString) {
        localStorage.setItem(STORAGE_KEYS.blockedUntil, isoString);
    } else {
        localStorage.removeItem(STORAGE_KEYS.blockedUntil);
    }
}
