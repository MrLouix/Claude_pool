/** Thread panel view — displays subtasks and replies for a message thread. */

import * as api from '../api.js';
import { subscribe } from '../store.js';

// ── Module state ──────────────────────────────────────────────────────────────

let _rootMessageId = null;
let _chatId = null;
let _panel = null;
let _touchStartX = null;
let _unsubs = [];

// ── Public API ──────────────────────────────────────────────────────────────

export async function mount(_params) {
    // Router compatibility placeholder
}

// ── Initialization ──────────────────────────────────────────────────────────

function _init() {
    window.addEventListener('open-thread', ev => _open(ev.detail.messageId));
}

// Only initialize once
_init();

// ── Open thread panel ────────────────────────────────────────────────────────

async function _open(messageId) {
    _rootMessageId = messageId;
    
    // Get chatId from current router state or fetch the root message
    const response = await api.get(`/api/messages/${messageId}/thread`);
    const data = await response.json();
    
    _chatId = data.root?.chat_id || _chatId;
    
    // Create panel if it doesn't exist
    if (!_panel) {
        _panel = document.createElement('div');
        _panel.id = 'thread-panel';
        document.body.appendChild(_panel);
    }
    
    // Render panel content
    _renderPanel(data);
    
    // Show panel
    document.body.classList.add('thread-open');
    _panel.classList.add('thread-panel--visible');
    
    // Bind events
    _bindPanelEvents();
    _bindMobileSwipe();
    _bindWsEvents();
}

// ── Close thread panel ───────────────────────────────────────────────────────

function _close() {
    document.body.classList.remove('thread-open');
    if (_panel) {
        _panel.classList.remove('thread-panel--visible');
    }
    _unbindWsEvents();
}

// ── Render panel ────────────────────────────────────────────────────────────

function _renderPanel(data) {
    const root = data.root || {};
    const subtasks = data.subtasks || [];
    const messages = data.messages || [];
    
    const rootRole = root.role === 'user' ? 'You' : 'Assistant';
    const rootTime = root.created_at 
        ? new Date(root.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        : '';
    
    // Group subtasks by parent_task_id
    const topLevel = subtasks.filter(t => t.parent_task_id === null);
    const subtaskMap = new Map();
    subtasks.filter(t => t.parent_task_id !== null).forEach(t => {
        if (!subtaskMap.has(t.parent_task_id)) {
            subtaskMap.set(t.parent_task_id, []);
        }
        subtaskMap.get(t.parent_task_id).push(t);
    });
    
    // Build subtasks HTML
    let subtasksHtml = '';
    if (topLevel.length > 0) {
        subtasksHtml += `<div class="thread-section"><div class="thread-section-header">Subtasks</div>`;
        
        for (const task of topLevel) {
            subtasksHtml += _taskCardHtml(task);
            const children = subtaskMap.get(task.id) || [];
            for (const child of children) {
                subtasksHtml += _taskCardHtml(child, true);
            }
        }
        
        subtasksHtml += `</div>`;
    }
    
    // Build messages HTML
    const messagesHtml = messages.length > 0 
        ? `<div class="thread-section"><div class="thread-section-header">Replies</div>` +
          messages.map(m => _msgHTML(m)).join('') +
          `</div>`
        : '';
    
    _panel.innerHTML = `
        <div class="thread-header">
            <span class="thread-header-label">Thread</span>
            <button class="thread-close-btn" aria-label="Close thread">×</button>
        </div>
        <div class="thread-scroll-content">
            <div class="thread-root-card">
                <div class="thread-root-meta">
                    <span class="thread-root-role">${_esc(rootRole)}</span>
                    <span class="thread-root-time">${_esc(rootTime)}</span>
                </div>
                <div class="thread-root-content">${_renderMarkdown(root.content || '')}</div>
            </div>
            ${subtasksHtml}
            ${messagesHtml}
        </div>
        <div class="thread-composer">
            <textarea id="thread-composer-textarea" class="thread-composer-textarea"
                placeholder="Reply in thread..." rows="1"
                aria-label="Reply in thread"></textarea>
            <button id="thread-send-btn" class="thread-send-btn btn-primary"
                aria-label="Send reply" type="button">➤</button>
        </div>
    `;
    
    // Bind composer events
    const ta = _panel.querySelector('#thread-composer-textarea');
    const btn = _panel.querySelector('#thread-send-btn');
    
    if (ta) {
        ta.addEventListener('input', () => {
            ta.style.height = 'auto';
            const lineH = parseFloat(getComputedStyle(ta).lineHeight) || 20;
            ta.style.height = Math.min(ta.scrollHeight, lineH * 4) + 'px';
        });
        ta.addEventListener('keydown', e => {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); _sendReply(ta); }
        });
    }
    if (btn) {
        btn.addEventListener('click', () => _sendReply(ta));
    }
}

function _taskCardHtml(task, isSubtask = false) {
    const statusIcon = _getStatusIcon(task.status);
    const truncatedPrompt = (task.prompt || '').length > 80 
        ? (task.prompt || '').substring(0, 77) + '...' 
        : (task.prompt || '');
    
    let badge = '';
    if (task.subtask_count && task.subtask_count > 0) {
        const done = task.subtask_done_count || 0;
        badge = `<span class="thread-task-badge">${done}/${task.subtask_count} ✓</span>`;
    }
    
    return `
        <div class="thread-task-card${isSubtask ? ' thread-task--subtask' : ''}" data-task-id="${_esc(task.id)}">
            <span class="thread-task-status" aria-label="${_esc(task.status)}">${statusIcon}</span>
            <div class="thread-task-info">
                <span class="thread-task-prompt">${_esc(truncatedPrompt)}</span>
                ${badge}
            </div>
        </div>
    `;
}

function _getStatusIcon(status) {
    const icons = {
        pending: '⏳',
        running: '▶️',
        success: '✓',
        failed: '✗',
        skipped: '—',
        rate_limit_retry: '⏳'
    };
    return icons[status] || '❓';
}

function _msgHTML(msg) {
    const isUser = msg.role === 'user';
    const time = msg.created_at
        ? new Date(msg.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        : '';
    const roleLabel = isUser ? 'You' : 'Assistant';
    
    return `
        <div class="thread-msg-row" data-msg-id="${_esc(msg.id)}">
            <div class="thread-msg-avatar">${isUser ? '👤' : '🤖'}</div>
            <div class="thread-msg-body">
                <div class="thread-msg-meta">
                    <span class="thread-msg-role">${_esc(roleLabel)}</span>
                    <span class="thread-msg-time">${_esc(time)}</span>
                </div>
                <div class="thread-msg-content">${_renderMarkdown(msg.content || '')}</div>
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

// ── Send reply ──────────────────────────────────────────────────────────────

async function _sendReply(ta) {
    if (!ta || !_chatId || !_rootMessageId) return;
    
    const content = ta.value.trim();
    if (!content) return;
    
    ta.value = '';
    ta.style.height = 'auto';
    
    try {
        await api.post(`/api/chats/${_chatId}/messages`, {
            content,
            thread_root_id: _rootMessageId
        });
    } catch (err) {
        console.error('Failed to send thread reply:', err);
    }
}

// ── Event binding ────────────────────────────────────────────────────────────

function _bindPanelEvents() {
    const closeBtn = _panel?.querySelector('.thread-close-btn');
    closeBtn?.addEventListener('click', _close);
}

function _bindMobileSwipe() {
    if (!_panel) return;
    
    _panel.addEventListener('touchstart', (e) => {
        _touchStartX = e.touches[0].clientX;
    }, { passive: true });
    
    _panel.addEventListener('touchmove', (e) => {
        if (_touchStartX === null) return;
        const deltaX = e.touches[0].clientX - _touchStartX;
        // Swipe right to dismiss (deltaX > 60)
        if (deltaX > 60) {
            _close();
            _touchStartX = null;
        }
    }, { passive: true });
    
    _panel.addEventListener('touchend', () => {
        _touchStartX = null;
    }, { passive: true });
    
    _panel.addEventListener('touchcancel', () => {
        _touchStartX = null;
    }, { passive: true });
}

// ── WebSocket events ─────────────────────────────────────────────────────────

function _bindWsEvents() {
    _unsubs = [
        subscribe('ws_event', (msg) => {
            if (!msg || !msg.event) return;
            
            // Task status updates
            if (msg.event === 'pool:task_started' || 
                msg.event === 'pool:task_completed' || 
                msg.event === 'pool:task_failed') {
                const taskId = msg.data?.task_id || msg.data?.id;
                if (taskId) {
                    _updateTaskStatus(taskId, msg.data?.status || msg.event.split(':')[1]);
                }
            }
        }),
        window.addEventListener('pool:message_created', (ev) => {
            const data = ev.detail?.data || {};
            if (data.thread_root_id === _rootMessageId) {
                _appendMessage(data);
            }
        })
    ];
}

function _unbindWsEvents() {
    _unsubs.forEach(fn => {
        if (typeof fn === 'function') fn();
    });
    _unsubs = [];
    window.removeEventListener('pool:message_created', () => {});
}

function _updateTaskStatus(taskId, status) {
    if (!_panel) return;
    const card = _panel.querySelector(`[data-task-id="${_esc(taskId)}"]`);
    if (card) {
        const statusEl = card.querySelector('.thread-task-status');
        if (statusEl) {
            statusEl.textContent = _getStatusIcon(status);
            statusEl.setAttribute('aria-label', _esc(status));
        }
    }
}

function _appendMessage(data) {
    if (!_panel) return;
    
    const messagesSection = _panel.querySelector('.thread-section:last-child');
    if (!messagesSection) return;
    
    // Check if this is a replies section
    const header = messagesSection.querySelector('.thread-section-header');
    if (header && header.textContent.includes('Replies')) {
        const msgHtml = _msgHTML({
            id: data.id,
            role: data.role,
            content: data.content,
            created_at: data.created_at
        });
        // Insert before the closing div of the section
        messagesSection.insertAdjacentHTML('beforeend', msgHtml);
    }
}

// ── Utility ───────────────────────────────────────────────────────────────────

function _esc(str) {
    return String(str ?? '')
        .replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
