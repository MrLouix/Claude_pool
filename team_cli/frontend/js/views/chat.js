/** Chat view: tab bar + paginated message list + real-time composer. */

import * as api from '../api.js';
import {
    loadChats, getChats,
    loadCliCommands, getCliCommands,
    subscribe,
} from '../store.js';

// ── Module state ──────────────────────────────────────────────────────────────

let _projectId    = null;
let _chatId       = null;
let _container    = null;
let _messages     = [];
let _hasMore      = false;
let _cursorBefore = null;
let _isRunning    = false;
let _unsubs       = [];
let _longPressTimer = null;

// ── Public API ────────────────────────────────────────────────────────────────

export async function mount(params) {
    _cleanup();
    _projectId    = params.projectId;
    _chatId       = params.chatId;
    _messages     = [];
    _hasMore      = false;
    _cursorBefore = null;
    _isRunning    = false;

    _container = document.querySelector('.center-zone');
    if (!_container) return;

    _container.innerHTML = _shellHTML();

    await Promise.all([loadChats(_projectId), loadCliCommands()]);

    _renderTabs(getChats(_projectId));
    await _fetchMessages();
    _renderMessages();
    _renderComposer();
    _bindComposerEvents();
    _scrollBottom();

    _unsubs.push(
        subscribe('chats', data => {
            if (data.projectId === _projectId) _renderTabs(data.chats);
        })
    );

    window.addEventListener('pool:message_created', _onWsMsgCreated);

    if (window.visualViewport) {
        window.visualViewport.addEventListener('resize', _onViewportResize);
    }
}

// ── Cleanup ───────────────────────────────────────────────────────────────────

function _cleanup() {
    _unsubs.forEach(fn => fn());
    _unsubs = [];
    window.removeEventListener('pool:message_created', _onWsMsgCreated);
    if (window.visualViewport) {
        window.visualViewport.removeEventListener('resize', _onViewportResize);
    }
    if (_longPressTimer) { clearTimeout(_longPressTimer); _longPressTimer = null; }
}

// ── Shell ─────────────────────────────────────────────────────────────────────

function _shellHTML() {
    return `
        <div class="chat-tab-bar" role="tablist" aria-label="Chats"></div>
        <div class="chat-messages" id="chat-msg-list"
             role="log" aria-live="polite" aria-label="Messages"></div>
        <div class="chat-composer" id="chat-composer"></div>
    `;
}

// ── Tab bar ───────────────────────────────────────────────────────────────────

function _renderTabs(chats) {
    const bar = _container?.querySelector('.chat-tab-bar');
    if (!bar || !chats) return;

    bar.innerHTML = chats.map(_tabHTML).join('') + `
        <button class="chat-tab-add" id="chat-tab-add"
            aria-label="New chat" tabindex="0">＋</button>
    `;

    bar.querySelectorAll('.chat-tab').forEach(_bindTabItemEvents);
    bar.querySelector('#chat-tab-add')?.addEventListener('click', _onAddTab);
    bar.querySelector('#chat-tab-add')?.addEventListener('keydown', e => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); _onAddTab(); }
    });

    bar.querySelector('.chat-tab.active')?.scrollIntoView({ inline: 'nearest', block: 'nearest' });
}

function _tabHTML(c) {
    const active = c.id === _chatId;
    return `
        <div class="chat-tab${active ? ' active' : ''}"
             role="tab" aria-selected="${active}"
             data-chat-id="${_esc(c.id)}" tabindex="${active ? '0' : '-1'}"
             draggable="true">
            <span class="chat-tab-label">${_esc(c.label)}</span>
            <button class="chat-tab-close" data-chat-id="${_esc(c.id)}"
                aria-label="Close ${_esc(c.label)}" tabindex="-1">✕</button>
        </div>
    `;
}

function _bindTabItemEvents(tabEl) {
    tabEl.addEventListener('click', e => {
        if (e.target.classList.contains('chat-tab-close')) return;
        const id = tabEl.dataset.chatId;
        if (id !== _chatId) location.hash = `#/p/${_projectId}/c/${id}`;
    });

    tabEl.querySelector('.chat-tab-close')?.addEventListener('click', e => {
        e.stopPropagation();
        _onCloseTab(tabEl.dataset.chatId);
    });

    // Rename: double-click (desktop) / long-press 500 ms (mobile)
    tabEl.addEventListener('dblclick', () => _startTabRename(tabEl));
    tabEl.addEventListener('touchstart', () => {
        _longPressTimer = setTimeout(() => _startTabRename(tabEl), 500);
    }, { passive: true });
    tabEl.addEventListener('touchend', () => {
        clearTimeout(_longPressTimer); _longPressTimer = null;
    }, { passive: true });
    tabEl.addEventListener('touchmove', () => {
        clearTimeout(_longPressTimer); _longPressTimer = null;
    }, { passive: true });

    // Drag-and-drop reorder (desktop)
    tabEl.addEventListener('dragstart', e => {
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', tabEl.dataset.chatId);
    });
    tabEl.addEventListener('dragover', e => {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        tabEl.classList.add('drag-over');
    });
    tabEl.addEventListener('dragleave', () => tabEl.classList.remove('drag-over'));
    tabEl.addEventListener('drop', async e => {
        e.preventDefault();
        tabEl.classList.remove('drag-over');
        const srcId = e.dataTransfer.getData('text/plain');
        const dstId = tabEl.dataset.chatId;
        if (srcId && srcId !== dstId) {
            const dstPos = getChats(_projectId).find(c => c.id === dstId)?.position ?? 0;
            try {
                await api.chats.update(srcId, { position: dstPos });
                await loadChats(_projectId);
            } catch (err) { console.error('Tab reorder failed:', err); }
        }
    });

    // Keyboard nav within tab bar
    tabEl.addEventListener('keydown', e => {
        const bar  = tabEl.closest('.chat-tab-bar');
        const tabs = [...bar.querySelectorAll('.chat-tab')];
        const idx  = tabs.indexOf(tabEl);
        if (e.key === 'ArrowRight') { tabs[idx + 1]?.focus(); e.preventDefault(); }
        if (e.key === 'ArrowLeft')  { tabs[idx - 1]?.focus(); e.preventDefault(); }
        if (e.key === 'Enter' || e.key === ' ') { tabEl.click(); e.preventDefault(); }
        if (e.key === 'Delete')     { _onCloseTab(tabEl.dataset.chatId); e.preventDefault(); }
    });
}

async function _onAddTab() {
    try {
        const n    = getChats(_projectId).length + 1;
        const chat = await api.chats.createInProject(_projectId, { label: `Chat ${n}` });
        await loadChats(_projectId);
        location.hash = `#/p/${_projectId}/c/${chat.id}`;
    } catch (err) { console.error('Failed to create chat:', err); }
}

async function _onCloseTab(chatId) {
    const chats = getChats(_projectId);
    if (chats.length <= 1) { alert('Cannot close the last chat.'); return; }
    if (!confirm('Close this chat?')) return;
    try {
        await api.chats.delete(chatId);
        const remaining = chats.filter(c => c.id !== chatId);
        await loadChats(_projectId);
        if (chatId === _chatId) {
            const next = remaining[0];
            location.hash = next ? `#/p/${_projectId}/c/${next.id}` : `#/p/${_projectId}`;
        }
    } catch (err) { console.error('Failed to close chat:', err); }
}

function _startTabRename(tabEl) {
    const labelEl = tabEl.querySelector('.chat-tab-label');
    if (!labelEl) return;
    const cur    = labelEl.textContent;
    const input  = document.createElement('input');
    input.type       = 'text';
    input.value      = cur;
    input.className  = 'chat-tab-rename-input';
    input.setAttribute('aria-label', 'Rename chat');
    labelEl.replaceWith(input);
    input.focus();
    input.select();

    const commit = async () => {
        const newLabel = input.value.trim() || cur;
        try {
            await api.chats.update(tabEl.dataset.chatId, { label: newLabel });
            await loadChats(_projectId);
        } catch (err) { console.error('Rename failed:', err); }
    };
    input.addEventListener('blur', commit);
    input.addEventListener('keydown', e => {
        if (e.key === 'Enter')  { e.preventDefault(); input.blur(); }
        if (e.key === 'Escape') { input.value = cur;  input.blur(); }
    });
}

// ── Messages fetch & pagination ───────────────────────────────────────────────

async function _fetchMessages(prepend = false) {
    const params = { limit: 50 };
    if (prepend && _cursorBefore) params.before = _cursorBefore;

    const page  = await api.messages.listPage(_chatId, params);
    const items = page.items ?? page;
    _hasMore    = page.has_more ?? false;

    if (prepend) {
        _messages     = [...items, ..._messages];
        _cursorBefore = items[0]?.id ?? _cursorBefore;
    } else {
        // Lazy rendering: keep only 100 most recent in the DOM
        const all     = items.length > 100 ? items.slice(items.length - 100) : items;
        _messages     = all;
        _cursorBefore = all[0]?.id ?? null;
    }
}

async function _onLoadEarlier() {
    const list          = document.getElementById('chat-msg-list');
    const prevScrollH   = list?.scrollHeight ?? 0;
    await _fetchMessages(true);
    _renderMessages();
    if (list) list.scrollTop = list.scrollHeight - prevScrollH;
}

// ── Message rendering ─────────────────────────────────────────────────────────

function _renderMessages() {
    const list = document.getElementById('chat-msg-list');
    if (!list) return;

    const loadBtn = _hasMore
        ? `<button class="chat-load-earlier" id="chat-load-earlier"
               aria-label="Load earlier messages">Load earlier</button>`
        : '';
    const typing = _isRunning
        ? `<div class="chat-typing-indicator" aria-live="polite" aria-label="Assistant is typing">
               <span></span><span></span><span></span>
           </div>`
        : '';

    list.innerHTML = loadBtn + _messages.map(_msgHTML).join('') + typing;

    list.querySelector('#chat-load-earlier')?.addEventListener('click', _onLoadEarlier);

    list.querySelectorAll('.chat-thread-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            window.dispatchEvent(new CustomEvent('open-thread', {
                detail: { messageId: btn.dataset.msgId },
            }));
        });
    });
}

function _msgHTML(msg) {
    const isUser = msg.role === 'user';
    const time   = msg.created_at
        ? new Date(msg.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        : '';
    const replyCount = msg.reply_count || 0;
    const badgeText = replyCount > 0 ? `💬 ${replyCount}` : '💬';

    return `
        <div class="chat-msg-row chat-msg-${_esc(msg.role)}" data-msg-id="${_esc(msg.id)}">
            <div class="chat-msg-avatar" aria-hidden="true">${isUser ? '👤' : '🤖'}</div>
            <div class="chat-msg-body">
                <div class="chat-msg-meta">
                    <span class="chat-msg-role">${isUser ? 'You' : 'Assistant'}</span>
                    <span class="chat-msg-time">${time}</span>
                </div>
                <div class="chat-msg-content">${_renderMarkdown(msg.content || '')}</div>
                <button class="chat-thread-btn" data-msg-id="${_esc(msg.id)}" data-reply-count="${replyCount}"
                    aria-label="Open thread for this message">${badgeText}</button>
            </div>
        </div>
    `;
}

function _renderMarkdown(text) {
    const safe = text
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    return safe
        .replace(/```([\s\S]*?)```/g, (_, c) => `<pre><code>${c.trim()}</code></pre>`)
        .replace(/`([^`\n]+)`/g, '<code>$1</code>')
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.+?)\*/g, '<em>$1</em>')
        .replace(/\n/g, '<br>');
}

// ── Composer ──────────────────────────────────────────────────────────────────

function _renderComposer() {
    const el = document.getElementById('chat-composer');
    if (!el) return;
    const clis       = getCliCommands().filter(c => c.enabled);
    const cliOpts    = clis.map(c => `<option value="${_esc(c.id)}">${_esc(c.name)}</option>`).join('');
    const firstCli   = clis[0];
    const modelOpts  = firstCli
        ? (firstCli.models || []).map(m =>
            `<option value="${_esc(m)}"${m === firstCli.default_model ? ' selected' : ''}>${_esc(m)}</option>`
          ).join('')
        : '';
    const selectors = cliOpts
        ? `<select class="composer-cli-sel composer-select" aria-label="CLI">${cliOpts}</select>
           <select class="composer-model-sel composer-select" aria-label="Model">${modelOpts}</select>`
        : '';

    el.innerHTML = `
        <div class="composer-mobile-settings">
            <button class="composer-settings-toggle" id="composer-settings-toggle"
                aria-expanded="false" aria-controls="composer-picker"
                aria-label="CLI and model settings">⚙</button>
            <div class="composer-picker" id="composer-picker" hidden>
                <div class="composer-picker-inner">${selectors}</div>
            </div>
        </div>
        <div class="composer-row" role="group" aria-label="Message composer">
            <div class="composer-desktop-selectors">${selectors}</div>
            <label class="sr-only" for="composer-textarea">Message</label>
            <textarea id="composer-textarea" class="composer-textarea"
                placeholder="Message…" rows="1"
                aria-label="Message" aria-multiline="true"></textarea>
            <button id="composer-send-btn" class="composer-send-btn btn-primary"
                aria-label="Send message" type="button">➤</button>
        </div>
    `;
}

function _bindComposerEvents() {
    const el = document.getElementById('chat-composer');
    if (!el) return;
    const ta     = el.querySelector('#composer-textarea');
    const btn    = el.querySelector('#composer-send-btn');
    const toggle = el.querySelector('#composer-settings-toggle');
    const picker = el.querySelector('#composer-picker');

    ta?.addEventListener('input', () => {
        ta.style.height = 'auto';
        const lineH = parseFloat(getComputedStyle(ta).lineHeight) || 20;
        ta.style.height = Math.min(ta.scrollHeight, lineH * 6) + 'px';
    });

    ta?.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); _sendMessage(); }
    });

    btn?.addEventListener('click', _sendMessage);

    toggle?.addEventListener('click', () => {
        if (!picker) return;
        const opening = picker.hidden;
        picker.hidden = !opening;
        toggle.setAttribute('aria-expanded', String(opening));
    });

    // CLI selection syncs model dropdown and both selector instances
    el.querySelectorAll('.composer-cli-sel').forEach(sel => {
        sel.addEventListener('change', () => {
            const cli = getCliCommands().find(c => c.id === sel.value);
            if (!cli) return;
            const opts = (cli.models || []).map(m =>
                `<option value="${_esc(m)}"${m === cli.default_model ? ' selected' : ''}>${_esc(m)}</option>`
            ).join('');
            el.querySelectorAll('.composer-model-sel').forEach(ms => { ms.innerHTML = opts; });
            el.querySelectorAll('.composer-cli-sel').forEach(cs => { if (cs !== sel) cs.value = sel.value; });
        });
    });
}

async function _sendMessage() {
    const el = document.getElementById('chat-composer');
    const ta = el?.querySelector('#composer-textarea');
    if (!ta || _isRunning) return;
    const content = ta.value.trim();
    if (!content) return;

    const cliSel   = el.querySelector('.composer-cli-sel');
    const modelSel = el.querySelector('.composer-model-sel');
    const body = {
        content,
        ...(cliSel?.value   ? { cli_id: cliSel.value }  : {}),
        ...(modelSel?.value ? { model: modelSel.value }  : {}),
    };

    ta.value        = '';
    ta.style.height = 'auto';
    _setRunning(true);

    try {
        const msg = await api.messages.create(_chatId, body);
        _messages.push(msg);
        _renderMessages();
        _scrollBottom();
    } catch (err) {
        console.error('Failed to send message:', err);
        _setRunning(false);
    }
}

// ── Running state & typing indicator ─────────────────────────────────────────

function _setRunning(val) {
    _isRunning = val;
    const el  = document.getElementById('chat-composer');
    const btn = el?.querySelector('#composer-send-btn');
    const ta  = el?.querySelector('#composer-textarea');
    if (btn) btn.disabled = val;
    if (ta)  ta.disabled  = val;

    const list = document.getElementById('chat-msg-list');
    if (!list) return;
    const existing = list.querySelector('.chat-typing-indicator');
    if (val && !existing) {
        const div = document.createElement('div');
        div.className = 'chat-typing-indicator';
        div.setAttribute('aria-live', 'polite');
        div.setAttribute('aria-label', 'Assistant is typing');
        div.innerHTML = '<span></span><span></span><span></span>';
        list.appendChild(div);
        _scrollBottom();
    } else if (!val && existing) {
        existing.remove();
    }
}

// ── WebSocket events ──────────────────────────────────────────────────────────

function _onWsMsgCreated(ev) {
    // ev.detail = { event: 'message_created', data: { message_id, chat_id, role, task_id } }
    const data = ev.detail?.data ?? {};
    if (data.chat_id !== _chatId) return;
    if (data.role !== 'user') _setRunning(false);

    // Update badge counter for thread parent if this is a threaded reply
    if (data.thread_root_id) {
        _updateThreadBadge(data.thread_root_id);
    }

    // Re-fetch latest messages from server
    api.messages.list(_chatId).then(items => {
        _messages = items.length > 100 ? items.slice(items.length - 100) : items;
        _renderMessages();
        _scrollBottom();
    }).catch(console.error);
}

function _updateThreadBadge(threadRootId) {
    const list = document.getElementById('chat-msg-list');
    if (!list) return;
    
    const parentRow = list.querySelector(`[data-msg-id="${_esc(threadRootId)}"]`);
    if (parentRow) {
        const btn = parentRow.querySelector('.chat-thread-btn');
        if (btn) {
            const current = parseInt(btn.dataset.replyCount || '0', 10);
            btn.dataset.replyCount = current + 1;
            btn.textContent = '💬 ' + (current + 1);
        }
    }
}

// ── Virtual keyboard adjustment ───────────────────────────────────────────────

function _onViewportResize() {
    const composer = document.getElementById('chat-composer');
    if (!composer || !window.visualViewport) return;
    const vv     = window.visualViewport;
    const offsetY = window.innerHeight - vv.height - vv.offsetTop;
    composer.style.transform = `translateY(-${Math.max(0, offsetY)}px)`;
}

// ── Scroll ────────────────────────────────────────────────────────────────────

function _scrollBottom() {
    const list = document.getElementById('chat-msg-list');
    if (list) list.scrollTop = list.scrollHeight;
}

// ── Utility ───────────────────────────────────────────────────────────────────

function _esc(str) {
    return String(str ?? '')
        .replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
