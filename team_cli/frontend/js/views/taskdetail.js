/** Task detail panel — shown when a queue card is clicked. */

// ── Public API ────────────────────────────────────────────────────────────────

export function showTaskDetail(task, projects) {
    _removeExisting();
    const panel = _buildPanel(task, projects);
    document.body.appendChild(panel);
    panel.querySelector('.task-detail-close')?.focus();
}

// ── Panel construction ────────────────────────────────────────────────────────

function _buildPanel(task, projects) {
    const overlay = document.createElement('div');
    overlay.className = 'task-detail-overlay';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-label', 'Task detail');

    overlay.innerHTML = `
        <div class="task-detail-panel">
            <div class="task-detail-header">
                <h3 class="task-detail-title">Task Detail</h3>
                <button class="task-detail-close btn btn-sm btn-secondary"
                    type="button" aria-label="Close task detail">✕</button>
            </div>
            <div class="task-detail-body">
                <div class="task-detail-prompt">${_esc(task.prompt || '')}</div>
                <div class="task-detail-meta">
                    ${_metaRows(task, projects)}
                </div>
                ${_reroutedSection(task)}
                ${_outputSection(task)}
                ${_threadLink(task)}
            </div>
        </div>
    `;

    overlay.querySelector('.task-detail-close').addEventListener('click', _removeExisting);
    overlay.addEventListener('click', e => {
        if (e.target === overlay) _removeExisting();
    });
    document.addEventListener('keydown', _onEsc);

    return overlay;
}

function _metaRows(task, projects) {
    const project = projects?.find(p => p.id === task.project_id);
    const rows = [
        ['Status',   task.status  || '—'],
        ['Kind',     task.kind    || '—'],
        ['Project',  project?.name || task.project_id || '—'],
        ['CLI',      task.cli_id  || '—'],
        ['Model',    task.model   || '—'],
        ['Duration', task.duration_ms != null ? _fmtDuration(task.duration_ms) : '—'],
    ];
    return rows.map(([label, val]) => `
        <div class="task-detail-row">
            <span class="task-detail-label">${_esc(label)}</span>
            <span class="task-detail-value">${_esc(String(val))}</span>
        </div>
    `).join('');
}

function _reroutedSection(task) {
    const parts = [];
    if (task.rerouted_from) {
        parts.push(`<div class="task-detail-row">
            <span class="task-detail-label">Rerouted from</span>
            <span class="task-detail-value">${_esc(task.rerouted_from)}</span>
        </div>`);
    }
    if (task.rerouted_to) {
        parts.push(`<div class="task-detail-row">
            <span class="task-detail-label">Rerouted to</span>
            <span class="task-detail-value">${_esc(task.rerouted_to)}</span>
        </div>`);
    }
    return parts.length ? `<div class="task-detail-rerouted">${parts.join('')}</div>` : '';
}

function _outputSection(task) {
    if (!task.json_output && task.json_output !== 0) return '';
    let content;
    try {
        const parsed = typeof task.json_output === 'string'
            ? JSON.parse(task.json_output)
            : task.json_output;
        content = `<pre class="task-detail-output">${_esc(JSON.stringify(parsed, null, 2))}</pre>`;
    } catch {
        content = `<pre class="task-detail-output">${_esc(String(task.json_output))}</pre>`;
    }
    return `<div class="task-detail-section">
        <div class="task-detail-section-label">Output</div>
        ${content}
    </div>`;
}

function _threadLink(task) {
    if (!task.chat_id) return '';
    const href = `#/p/${_esc(task.project_id || '')}/c/${_esc(task.chat_id)}`;
    return `<div class="task-detail-section">
        <a class="task-detail-thread-link" href="${href}">View in thread →</a>
    </div>`;
}

// ── Lifecycle helpers ─────────────────────────────────────────────────────────

function _removeExisting() {
    document.querySelectorAll('.task-detail-overlay').forEach(el => el.remove());
    document.removeEventListener('keydown', _onEsc);
}

function _onEsc(e) {
    if (e.key === 'Escape') _removeExisting();
}

// ── Formatting helpers ────────────────────────────────────────────────────────

function _fmtDuration(ms) {
    if (ms < 1000)  return `${ms}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    return `${Math.floor(ms / 60000)}m ${Math.floor((ms % 60000) / 1000)}s`;
}

function _esc(str) {
    return String(str ?? '')
        .replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
