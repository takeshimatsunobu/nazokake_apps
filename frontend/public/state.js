// frontend/public/state.js

// ユーザーIDがない場合は自動生成して保存
let storedSlug = localStorage.getItem('nazokake_user_slug');
if (!storedSlug) {
    storedSlug = 'user_' + Math.random().toString(36).substring(2, 11);
    localStorage.setItem('nazokake_user_slug', storedSlug);
}

export const appState = {
    isUserFeedLoaded: false,
    myRadarChart: null,
    humanRadarChart: null,
    userSlug: storedSlug,
    sessionStartTime: Date.now(),
    evaluatedItems: JSON.parse(localStorage.getItem('nazokake_evaluated')) || []
};