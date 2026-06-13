/** Settings view — CLI Commands and Priority Order. */

import * as api from '../api.js';

// ── State ─────────────────────────────────────────────────────────────────────

let _commands = [];  // server-confirmed list; updated after each save
let _settings = {};  // key→value from /api/settings
let _container = null;

// ── Public API ────────────────────────────────────────────────────────────────

export async function mount(params) {
    _container = (params && params.el) || document.querySelector('#app') || document.body;
    const [commands, settings] = await Promise.all([
        api.cliCommands.list().catch(() => []),
        api.settings.get().catch(() => ({})),
    ]);
    _commands = commands;
    _settings = settings;
    _render();
    await _initGeneral();
}

// ── Top-level render ──────────────────────────────────────────────────────────

function _render() {
    _container.innerHTML = `
        <div class="settings-view">
            <section class="settings-section">
                <div class="settings-section-header">
                    <h2>CLI Commands</h2>
                    <div class="settings-header-actions">
                        <button id="cli-add-btn" class="btn btn-secondary"
                            aria-label="Add CLI command" type="button">+ Add</button>
                        <button id="cli-save-btn" class="btn btn-primary"
                            aria-label="Save CLI commands" type="button">Save</button>
                    </div>
                </div>
                <div id="cli-cards-list"></div>
                <div id="cli-add-picker" class="cli-add-picker" hidden></div>
            </section>
            <section class="settings-section">
                <h2>Priority Order</h2>
                <div class="priority-lists">
                    <div class="priority-list-wrap">
                        <h3>Requests</h3>
                        <ul id="priority-requests-list" class="priority-list"></ul>
                        <p class="settings-hint">On rate limit, the next command in this list takes over.</p>
                    </div>
                    <div class="priority-list-wrap">
                        <h3>Subtasks</h3>
                        <ul id="priority-subtasks-list" class="priority-list"></ul>
                        <p class="settings-hint">On rate limit, the next command in this list takes over.</p>
                    </div>
                </div>
            </section>
            <section class="settings-section" id="general-section">
                <h2>General</h2>
                <div class="general-field-row">
                    <span class="general-field-label">Server port</span>
                    <span id="settings-port" class="general-field-value"></span>
                </div>
                <div class="general-field-row">
                    <label for="settings-max-workers" class="general-field-label">Max concurrent tasks</label>
                    <input type="number" id="settings-max-workers" class="general-field-input"
                        min="1" max="16" aria-label="Max concurrent tasks">
                </div>
                <div class="general-field-row">
                    <label for="settings-max-subtasks" class="general-field-label">Max subtasks per task</label>
                    <input type="number" id="settings-max-subtasks" class="general-field-input"
                        min="1" max="50" aria-label="Max subtasks per task">
                </div>
                <div class="general-field-row">
                    <label for="settings-auto-decompose" class="general-field-label">Auto-decompose subtasks</label>
                    <input type="checkbox" id="settings-auto-decompose"
                        aria-label="Auto-decompose subtasks">
                </div>
                <div class="general-field-row">
                    <button id="settings-purge-btn" class="btn btn-danger"
                        aria-label="Purge completed tasks" type="button">Purge completed tasks</button>
                    <span id="settings-purge-result" class="general-field-value" hidden></span>
                </div>
            </section>
        </div>
    `;

    const cardsList = _container.querySelector('#cli-cards-list');
    for (const cmd of _commands) {
        cardsList.appendChild(_makeCard(cmd));
    }

    _renderPriorityList('requests');
    _renderPriorityList('subtasks');

    _container.querySelector('#cli-add-btn').addEventListener('click', _showAddPicker);
    _container.querySelector('#cli-save-btn').addEventListener('click', () => _saveCommands(false));
}

// ── Card building ─────────────────────────────────────────────────────────────

function _makeCard(cmd) {
    const card = document.createElement('div');
    card.className = 'cli-card';
    card.dataset.cliId = String(cmd.id);
    card.dataset.models = JSON.stringify(cmd.models || []);

    const modelsArr = cmd.models || [];
    const parserCJ = cmd.parser === 'claude_json' ? ' selected' : '';
    const parserPL = cmd.parser === 'plain' ? ' selected' : '';

    card.innerHTML = `
        <div class="cli-card-header">
            <label class="cli-toggle-wrap">
                <input type="checkbox" class="cli-toggle"
                    aria-label="Enable ${_esc(cmd.name)}"${cmd.enabled ? ' checked' : ''}>
                <span class="cli-toggle-label">Enabled</span>
            </label>
            <div class="cli-card-name-row">
                <input type="text" class="cli-name"
                    value="${_esc(cmd.name)}" aria-label="Command name" placeholder="Name">
                <input type="text" class="cli-binary"
                    value="${_esc(cmd.binary)}" aria-label="Binary" placeholder="binary">
            </div>
            <div class="cli-card-actions">
                <button class="cli-test-btn btn btn-sm btn-secondary"
                    aria-label="Test ${_esc(cmd.name)}" type="button">Test</button>
                <button class="cli-delete-btn btn btn-sm btn-danger"
                    aria-label="Delete ${_esc(cmd.name)}" type="button">Delete</button>
            </div>
        </div>
        <div class="cli-test-result" hidden></div>
        <div class="cli-models-section">
            <div class="model-chips" role="list">${modelsArr.map(_chipHtml).join('')}</div>
            <div class="model-add-row">
                <input type="text" class="model-add-input"
                    placeholder="Add model..." aria-label="Add model">
                <select class="cli-default-model" aria-label="Default model">
                    ${_defaultModelOptions(modelsArr, cmd.default_model)}
                </select>
            </div>
        </div>
        <details class="cli-advanced">
            <summary class="cli-advanced-toggle">Advanced</summary>
            <div class="cli-advanced-body">
                <label class="cli-field-label">Args template
                    <textarea class="cli-args-template"
                        aria-label="Args template" rows="2">${_esc(cmd.args_template || '')}</textarea>
                </label>
                <label class="cli-field-label">Resume template
                    <textarea class="cli-resume-template"
                        aria-label="Resume template" rows="2">${_esc(cmd.resume_template || '')}</textarea>
                </label>
                <label class="cli-field-label">Output parser
                    <select class="cli-parser" aria-label="Output parser">
                        <option value="claude_json"${parserCJ}>Claude JSON</option>
                        <option value="plain"${parserPL}>Plain text</option>
                    </select>
                </label>
            </div>
        </details>
    `;

    _bindCardEvents(card);
    return card;
}

function _chipHtml(model) {
    return `<span class="model-chip" data-model="${_esc(model)}" role="listitem">`
        + `${_esc(model)} <button class="model-chip-remove" type="button"`
        + ` aria-label="Remove model ${_esc(model)}">×</button></span>`;
}

function _defaultModelOptions(models, defaultModel) {
    const opts = ['<option value="">— none —</option>'];
    for (const m of models) {
        opts.push(`<option value="${_esc(m)}"${m === defaultModel ? ' selected' : ''}>${_esc(m)}</option>`);
    }
    return opts.join('');
}

function _bindCardEvents(card) {
    card.querySelector('.cli-test-btn').addEventListener('click', () => _testCli(card));
    card.querySelector('.cli-delete-btn').addEventListener('click', () => card.remove());

    // Chip removal (delegated)
    card.querySelector('.model-chips').addEventListener('click', e => {
        const btn = e.target.closest('.model-chip-remove');
        if (!btn) return;
        const chip = btn.closest('.model-chip');
        if (!chip) return;
        _setModels(card, _getModels(card).filter(m => m !== chip.dataset.model));
    });

    // Add model on Enter
    card.querySelector('.model-add-input').addEventListener('keydown', e => {
        if (e.key !== 'Enter') return;
        e.preventDefault();
        const val = e.target.value.trim();
        if (!val) return;
        const models = _getModels(card);
        if (!models.includes(val)) _setModels(card, [...models, val]);
        e.target.value = '';
    });
}

function _getModels(card) {
    try { return JSON.parse(card.dataset.models || '[]'); } catch { return []; }
}

function _setModels(card, models) {
    card.dataset.models = JSON.stringify(models);
    const currentDefault = card.querySelector('.cli-default-model').value;
    card.querySelector('.model-chips').innerHTML = models.map(_chipHtml).join('');
    card.querySelector('.cli-default-model').innerHTML = _defaultModelOptions(models, currentDefault);
}

// ── Add picker ────────────────────────────────────────────────────────────────

const _PRESETS = [
    { label: 'Claude Code', id: 'claude', binary: 'claude',
      args_template: '["-p","{prompt}","--output-format","json"]', parser: 'claude_json' },
    { label: 'Codex CLI',   id: 'codex',  binary: 'codex',
      args_template: '["-p","{prompt}"]', parser: 'plain' },
    { label: 'Gemini CLI',  id: 'gemini', binary: 'gemini',
      args_template: '["--prompt","{prompt}"]', parser: 'plain' },
    { label: 'Custom',      id: null,     binary: '',
      args_template: '', parser: 'plain' },
];

function _showAddPicker() {
    const picker = _container.querySelector('#cli-add-picker');
    if (!picker.hidden) { picker.hidden = true; return; }

    picker.innerHTML = _PRESETS.map((p, i) =>
        `<button class="cli-preset-btn btn btn-sm btn-secondary"
            data-preset="${i}" type="button">${_esc(p.label)}</button>`
    ).join('');
    picker.hidden = false;

    picker.addEventListener('click', e => {
        const btn = e.target.closest('.cli-preset-btn');
        if (!btn) return;
        const preset = _PRESETS[parseInt(btn.dataset.preset, 10)];
        const newId = preset.id || ('custom_' + Date.now());
        _container.querySelector('#cli-cards-list').appendChild(_makeCard({
            id: newId,
            name: preset.label === 'Custom' ? '' : preset.label,
            binary: preset.binary,
            args_template: preset.args_template,
            resume_template: null,
            model_flag: null,
            models: [],
            default_model: null,
            enabled: true,
            priority_requests: 100,
            priority_subtasks: 100,
            parser: preset.parser,
        }));
        picker.hidden = true;
    }, { once: true });
}

// ── Test CLI ──────────────────────────────────────────────────────────────────

async function _testCli(card) {
    const resultEl = card.querySelector('.cli-test-result');
    resultEl.hidden = false;
    resultEl.className = 'cli-test-result';
    resultEl.textContent = 'Testing…';
    try {
        const res = await api.cliCommands.test(card.dataset.cliId);
        if (res.success) {
            resultEl.textContent = `OK: ${res.output}`;
            resultEl.classList.add('cli-test-ok');
        } else {
            resultEl.textContent = `Error: ${res.output}`;
            resultEl.classList.add('cli-test-err');
        }
    } catch (e) {
        resultEl.textContent = `Error: ${e.message}`;
        resultEl.classList.add('cli-test-err');
    }
}

// ── Collect & Save ────────────────────────────────────────────────────────────

function _collectCommands() {
    // Build priority index from the priority list DOM order
    const reqPriority = {};
    const subPriority = {};
    _container.querySelectorAll('#priority-requests-list .priority-item').forEach((li, i) => {
        reqPriority[li.dataset.cliId] = i + 1;
    });
    _container.querySelectorAll('#priority-subtasks-list .priority-item').forEach((li, i) => {
        subPriority[li.dataset.cliId] = i + 1;
    });

    return Array.from(_container.querySelectorAll('.cli-card')).map(card => {
        const id = card.dataset.cliId;
        return {
            id,
            name:             card.querySelector('.cli-name').value.trim(),
            binary:           card.querySelector('.cli-binary').value.trim(),
            args_template:    card.querySelector('.cli-args-template').value.trim(),
            resume_template:  card.querySelector('.cli-resume-template').value.trim() || null,
            model_flag:       null,
            models:           _getModels(card),
            default_model:    card.querySelector('.cli-default-model').value || null,
            enabled:          card.querySelector('.cli-toggle').checked,
            priority_requests: reqPriority[id] || 100,
            priority_subtasks: subPriority[id] || 100,
            parser:           card.querySelector('.cli-parser').value,
        };
    });
}

async function _saveCommands(silent) {
    const saveBtn = _container && _container.querySelector('#cli-save-btn');
    try {
        _commands = await api.cliCommands.update(_collectCommands());
        if (!silent && saveBtn) {
            const orig = saveBtn.textContent;
            saveBtn.textContent = 'Saved ✓';
            saveBtn.disabled = true;
            setTimeout(() => { saveBtn.textContent = orig; saveBtn.disabled = false; }, 1500);
        }
        // Refresh priority lists from server-confirmed state
        _renderPriorityList('requests');
        _renderPriorityList('subtasks');
    } catch (e) {
        console.error('Failed to save CLI commands:', e);
        if (!silent && saveBtn) {
            const orig = saveBtn.textContent;
            saveBtn.textContent = 'Error!';
            setTimeout(() => { saveBtn.textContent = orig; }, 2000);
        }
    }
}

// ── Priority lists ────────────────────────────────────────────────────────────

function _renderPriorityList(type) {
    const list = _container.querySelector(`#priority-${type}-list`);
    if (!list) return;

    const field = type === 'requests' ? 'priority_requests' : 'priority_subtasks';
    const enabled = _commands.filter(c => c.enabled).sort((a, b) => a[field] - b[field]);

    list.innerHTML = '';
    for (const cmd of enabled) {
        const li = document.createElement('li');
        li.className = 'priority-item';
        li.dataset.cliId = String(cmd.id);
        li.draggable = true;
        li.innerHTML = `
            <button class="priority-up" type="button"
                aria-label="Move ${_esc(cmd.name)} up">↑</button>
            <span class="priority-name">${_esc(cmd.name)}</span>
            <button class="priority-down" type="button"
                aria-label="Move ${_esc(cmd.name)} down">↓</button>
        `;
        li.querySelector('.priority-up').addEventListener('click', () => _movePriority(li, -1));
        li.querySelector('.priority-down').addEventListener('click', () => _movePriority(li, +1));
        list.appendChild(li);
    }

    _bindDragDrop(list);
}

function _movePriority(li, delta) {
    const list = li.parentElement;
    const items = Array.from(list.children);
    const idx = items.indexOf(li);
    const newIdx = idx + delta;
    if (newIdx < 0 || newIdx >= items.length) return;
    if (delta < 0) {
        list.insertBefore(li, items[newIdx]);
    } else {
        list.insertBefore(items[newIdx], li);
    }
    _saveCommands(true);
}

function _bindDragDrop(list) {
    let _dragSrc = null;

    list.addEventListener('dragstart', e => {
        _dragSrc = e.target.closest('.priority-item');
        if (_dragSrc) e.dataTransfer.effectAllowed = 'move';
    });

    list.addEventListener('dragover', e => {
        e.preventDefault();
        if (!_dragSrc) return;
        e.dataTransfer.dropEffect = 'move';
        const target = e.target.closest('.priority-item');
        if (!target || target === _dragSrc) return;
        const rect = target.getBoundingClientRect();
        if (e.clientY < rect.top + rect.height / 2) {
            list.insertBefore(_dragSrc, target);
        } else {
            list.insertBefore(_dragSrc, target.nextSibling);
        }
    });

    list.addEventListener('drop', e => {
        e.preventDefault();
        _saveCommands(true);
        _dragSrc = null;
    });

    list.addEventListener('dragend', () => { _dragSrc = null; });
}

// ── General section ───────────────────────────────────────────────────────────

async function _initGeneral() {
    // Port
    const portEl = _container.querySelector('#settings-port');
    if (portEl) portEl.textContent = window.location.port || '8000';

    // Check for running tasks → disable max_workers if any
    let hasRunning = false;
    try {
        const poolStatus = await api.pool.status();
        hasRunning = !!(poolStatus && poolStatus.running > 0);
    } catch { /* ignore */ }

    // Max workers
    const mwEl = _container.querySelector('#settings-max-workers');
    if (mwEl) {
        mwEl.value = _settings['max_workers'] || '4';
        if (hasRunning) {
            mwEl.disabled = true;
            mwEl.title = 'Stop all tasks to change';
        }
        mwEl.addEventListener('change', async e => {
            await api.settings.update({ max_workers: e.target.value }).catch(console.error);
        });
    }

    // Max subtasks
    const msEl = _container.querySelector('#settings-max-subtasks');
    if (msEl) {
        msEl.value = _settings['max_subtasks_per_task'] || '10';
        msEl.addEventListener('change', async e => {
            await api.settings.update({ max_subtasks_per_task: e.target.value }).catch(console.error);
        });
    }

    // Auto decompose
    const adEl = _container.querySelector('#settings-auto-decompose');
    if (adEl) {
        adEl.checked = _settings['auto_decompose'] === 'true';
        adEl.addEventListener('change', async e => {
            await api.settings.update({ auto_decompose: e.target.checked ? 'true' : 'false' }).catch(console.error);
        });
    }

    // Purge button
    const purgeBtn = _container.querySelector('#settings-purge-btn');
    if (purgeBtn) purgeBtn.addEventListener('click', _purge);
}

async function _purge() {
    if (!window.confirm('Delete all completed tasks? This cannot be undone.')) return;
    const resultEl = _container.querySelector('#settings-purge-result');
    try {
        const [d1, d2] = await Promise.all([
            api.tasks.purge('success').catch(() => ({ deleted: 0 })),
            api.tasks.purge('failed').catch(() => ({ deleted: 0 })),
        ]);
        const total = (d1.deleted || 0) + (d2.deleted || 0);
        if (resultEl) { resultEl.hidden = false; resultEl.textContent = `Purged ${total} tasks`; }
    } catch (e) {
        if (resultEl) { resultEl.hidden = false; resultEl.textContent = `Error: ${e.message}`; }
    }
}

// ── Utility ───────────────────────────────────────────────────────────────────

function _esc(str) {
    return String(str ?? '')
        .replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
