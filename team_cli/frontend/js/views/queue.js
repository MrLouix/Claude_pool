/** Queue view — task list with filters, hierarchy, bulk actions, real-time updates. */

import * as api from '../api.js';
import { showTaskDetail } from './taskdetail.js';

// ── State ─────────────────────────────────────────────────────────────────────

let _tasks    = [];
let _projects = [];
let _cliMap   = {};  // cli_id → display name
let _filterStatus  = 'all';
let _filterProject = 'all';
let _container = null;

// ── Public API ────────────────────────────────────────────────────────────────

export async function mount(params) {
    _container = (params && params.el) || document.querySelector('#app') || document.body;
    await _loadAll();
    _render();
    _bindWsEvents();
}

export function cleanup() {
    _unbindWsEvents();
}

// ── Data loading ──────────────────────────────────────────────────────────────

async function _loadAll() {
    const [tasks, projects, cliCmds] = await Promise.all([
        api.tasks.list().catch(() => []),
        api.projects.list().catch(() => []),
        api.cliCommands.list().catch(() => []),
    ]);
    _tasks    = tasks;
    _projects = projects;
    _cliMap   = Object.fromEntries(cliCmds.map(c => [c.id, c.name]));
}

async function _refresh() {
    _tasks = await api.tasks.list().catch(() => _tasks);
    _render();
}

// ── Top-level render ──────────────────────────────────────────────────────────

function _render() {
    if (!_container) return;

    const filtered            = _applyFilters(_tasks);
    const { roots, childMap } = _buildHierarchy(filtered);

    _container.innerHTML = `
        <div class="queue-view">
            <div class="queue-header">
                <h2>Queue</h2>
                <div class="bulk-actions">
                    <button id="queue-clear-btn" class="btn btn-danger" type="button"
                        aria-label="Clear completed tasks">Clear completed</button>
                </div>
            </div>
            <div class="queue-filter-bar" role="toolbar" aria-label="Filter tasks">
                <div class="queue-filter-group">
                    <span class="queue-filter-label">Status</span>
                    ${['all','pending','running','completed','failed','skipped'].map(s =>
                        `<button class="queue-filter-btn${_filterStatus === s ? ' active' : ''}"
                            data-filter-status="${s}" type="button"
                            aria-pressed="${_filterStatus === s}">${_cap(s)}</button>`
                    ).join('')}
                </div>
                <div class="queue-filter-group">
                    <span class="queue-filter-label">Project</span>
                    <select id="queue-project-filter" class="queue-filter-select"
                        aria-label="Filter by project">
                        <option value="all"${_filterProject === 'all' ? ' selected' : ''}>All</option>
                        ${_projects.map(p =>
                            `<option value="${_esc(p.id)}"${_filterProject === p.id ? ' selected' : ''}>${_esc(p.name)}</option>`
                        ).join('')}
                    </select>
                </div>
            </div>
            <div id="queue-task-list" class="queue-task-list">
                ${roots.length === 0
                    ? '<div class="queue-empty">No tasks match the current filter.</div>'
                    : roots.map(t => _renderTree(t, childMap)).join('')}
            </div>
        </div>
    `;

    // Status filter buttons
    _container.querySelectorAll('.queue-filter-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            _filterStatus = btn.dataset.filterStatus;
            _render();
        });
    });

    // Project filter select
    _container.querySelector('#queue-project-filter')?.addEventListener('change', e => {
        _filterProject = e.target.value;
        _render();
    });

    // Bulk clear
    _container.querySelector('#queue-clear-btn')?.addEventListener('click', _clearCompleted);

    // Card clicks and skip buttons
    _container.querySelectorAll('.queue-card').forEach(card => {
        card.addEventListener('keydown', e => {
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); _openDetail(card); }
        });
        card.addEventListener('click', e => {
            if (!e.target.closest('.queue-card-skip-btn')) _openDetail(card);
        });
        card.querySelector('.queue-card-skip-btn')?.addEventListener('click', async e => {
            e.stopPropagation();
            try {
                await api.tasks.update(card.dataset.taskId, { status: 'skipped' });
                await _refresh();
            } catch (err) {
                console.error('Failed to skip task:', err);
            }
        });
    });
}

function _openDetail(card) {
    const task = _tasks.find(t => t.id === card.dataset.taskId);
    if (task) showTaskDetail(task, _projects);
}

// ── Filtering ─────────────────────────────────────────────────────────────────

function _applyFilters(tasks) {
    return tasks.filter(t => {
        if (_filterStatus !== 'all') {
            const internal = _filterStatus === 'completed' ? 'success' : _filterStatus;
            if (t.status !== internal) return false;
        }
        if (_filterProject !== 'all' && t.project_id !== _filterProject) return false;
        return true;
    });
}

// ── Hierarchy ─────────────────────────────────────────────────────────────────

function _buildHierarchy(tasks) {
    const ids = new Set(tasks.map(t => t.id));
    const roots    = tasks.filter(t => !t.parent_task_id || !ids.has(t.parent_task_id));
    const childMap = new Map();
    for (const t of tasks) {
        if (t.parent_task_id && ids.has(t.parent_task_id)) {
            if (!childMap.has(t.parent_task_id)) childMap.set(t.parent_task_id, []);
            childMap.get(t.parent_task_id).push(t);
        }
    }
    return { roots, childMap };
}

// ── Card rendering ────────────────────────────────────────────────────────────

function _renderTree(task, childMap) {
    const children = childMap.get(task.id) || [];
    return _cardHtml(task, false, children) +
           children.map(c => _cardHtml(c, true, [])).join('');
}

function _cardHtml(task, isSubtask, children) {
    const icon    = _statusIcon(task.status);
    const raw     = task.prompt || '';
    const prompt  = raw.length > 80 ? raw.substring(0, 77) + '…' : raw;
    const project = _projects.find(p => p.id === task.project_id);
    const meta    = [
        project?.name,
        task.cli_id && (_cliMap[task.cli_id] || task.cli_id),
        task.model,
        task.duration_ms != null && _fmtDuration(task.duration_ms),
    ].filter(Boolean).join(' · ');

    const kindLabel = task.kind === 'subtask' ? '[sub]' : '[req]';

    let progressBadge = '';
    if (children.length > 0) {
        const done = children.filter(c => c.status === 'success').length;
        progressBadge = `<span class="task-progress-badge">${done}/${children.length} ✓</span>`;
    }

    const skipBtn = task.status === 'pending'
        ? `<button class="queue-card-skip-btn btn btn-sm btn-secondary"
               type="button" aria-label="Skip task">Skip</button>`
        : '';

    return `
        <div class="queue-card${isSubtask ? ' queue-card--subtask' : ''}"
            data-task-id="${_esc(task.id)}" data-status="${_esc(task.status)}"
            role="button" tabindex="0" aria-label="Task: ${_esc(prompt)}">
            <div class="queue-card-left">
                <span class="status-icon" data-status="${_esc(task.status)}"
                    aria-label="${_esc(task.status)}">${icon}</span>
                <div class="queue-card-body">
                    <div class="task-prompt">${_esc(prompt)}</div>
                    ${meta ? `<div class="task-meta">${_esc(meta)}</div>` : ''}
                </div>
            </div>
            <div class="queue-card-right">
                <span class="task-kind">${kindLabel}</span>
                ${progressBadge}
                ${skipBtn}
            </div>
        </div>
    `;
}

// ── Bulk actions ──────────────────────────────────────────────────────────────

async function _clearCompleted() {
    if (!window.confirm('Delete all completed tasks? This cannot be undone.')) return;
    try {
        await api.tasks.purge('completed');
        await _refresh();
    } catch (err) {
        console.error('Failed to clear completed tasks:', err);
    }
}

// ── WebSocket events ──────────────────────────────────────────────────────────

function _onPoolStatus(ev) {
    const data = ev.detail;
    if (data && Array.isArray(data.tasks)) {
        _tasks = data.tasks;
        _render();
    } else {
        _refresh();
    }
}

function _bindWsEvents() {
    window.addEventListener('pool:pool_status', _onPoolStatus);
}

function _unbindWsEvents() {
    window.removeEventListener('pool:pool_status', _onPoolStatus);
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function _statusIcon(status) {
    const icons = { pending: '⏳', running: '▶️', success: '✓', failed: '✗',
                    skipped: '—', rate_limit_retry: '⏳' };
    return icons[status] || '❓';
}

function _fmtDuration(ms) {
    if (ms < 1000)  return `${ms}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    return `${Math.floor(ms / 60000)}m ${Math.floor((ms % 60000) / 1000)}s`;
}

function _cap(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

function _esc(str) {
    return String(str ?? '')
        .replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
