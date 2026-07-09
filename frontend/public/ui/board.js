// frontend/public/ui/board.js
// 掲示板の画面描画（View）をカプセル化。

window.uiRenderBoard = function(items) {
    const container = document.getElementById('board-container');
    if (!container) return;
    
    if (!items || items.length === 0) {
        container.innerHTML = '<div class="text-center py-10 text-gray-500">まだ投稿がありません。最初の話題を書き込んでみましょう！</div>';
        return;
    }

    const esc = window.uiEscapeHtml || ((s) => String(s == null ? '' : s));
    
    const html = items.map(item => {
        // 親投稿か返信かでのデザイン分岐
        const isReply = !!item.parent_id;
        const bgClass = isReply ? 'bg-gray-50 border-l-4 border-l-gray-400' : 'bg-white border border-[#C5B358]/50';
        const mlClass = isReply ? 'ml-8 mt-2' : 'mb-4';
        
        // 日付のフォーマット
        const dateObj = item.created_at ? new Date(item.created_at) : new Date();
        const dateStr = dateObj.toLocaleString('ja-JP', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
        
        return `
            <div class="${bgClass} ${mlClass} p-4 rounded-lg shadow-sm" id="board-post-${item.id}">
                <div class="flex justify-between items-center mb-2">
                    <span class="text-xs font-bold text-gray-500">ID: ${item.author_uid.substring(0, 6)}...</span>
                    <span class="text-[10px] text-gray-400">${dateStr}</span>
                </div>
                <div class="text-sm text-gray-800 whitespace-pre-wrap mb-3 leading-relaxed">${esc(item.body)}</div>
                
                ${!isReply ? `
                <div class="flex items-center justify-between border-t border-gray-100 pt-2 mt-2">
                    <span class="text-xs text-[#902A19] font-bold">🔥 盛り上がり: ${item.hot_score || 0}</span>
                    <button onclick="window.uiShowReplyForm('${item.id}')" class="text-xs text-[#5B8124] hover:underline flex items-center gap-1">
                        <span>💬 返信する</span>
                        <span class="bg-gray-200 text-gray-600 px-1.5 py-0.5 rounded-full text-[9px]">${item.reply_count || 0}</span>
                    </button>
                </div>
                <div id="reply-form-${item.id}" class="hidden mt-3 p-3 bg-gray-100 rounded border border-gray-200">
                    <textarea id="reply-input-${item.id}" rows="2" class="w-full p-2 text-xs border border-gray-300 rounded focus:outline-none focus:border-[#5B8124]" placeholder="返信を書き込む..."></textarea>
                    <div class="flex justify-end mt-2 gap-2">
                        <button onclick="window.uiHideReplyForm('${item.id}')" class="text-xs text-gray-500 hover:text-gray-700">キャンセル</button>
                        <button onclick="submitBoardPost('${item.id}')" class="text-xs bg-[#5B8124] text-white px-3 py-1 rounded hover:bg-[#4a6b1d]">送信</button>
                    </div>
                </div>
                ` : ''}
            </div>
        `;
    }).join('');

    container.innerHTML = html;
};

window.uiBoardShowLoading = function() {
    const c = document.getElementById('board-container');
    if (c) c.innerHTML = '<div class="flex justify-center py-10"><div class="animate-spin rounded-full h-8 w-8 border-b-2 border-[#902A19]"></div></div>';
};

window.uiShowReplyForm = function(postId) {
    document.getElementById(`reply-form-${postId}`)?.classList.remove('hidden');
    document.getElementById(`reply-input-${postId}`)?.focus();
};

window.uiHideReplyForm = function(postId) {
    document.getElementById(`reply-form-${postId}`)?.classList.add('hidden');
};

window.uiGetBoardInput = function(parentId = null) {
    const id = parentId ? `reply-input-${parentId}` : 'board-main-input';
    const el = document.getElementById(id);
    return el ? el.value.trim() : '';
};

window.uiClearBoardInput = function(parentId = null) {
    const id = parentId ? `reply-input-${parentId}` : 'board-main-input';
    const el = document.getElementById(id);
    if (el) el.value = '';
    if (parentId) window.uiHideReplyForm(parentId);
};
