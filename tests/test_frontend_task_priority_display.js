/**
 * Frontend unit tests for priority display and edit in task list + task detail.
 * Run with: node tests/test_frontend_task_priority_display.js
 */

// ── Minimal DOM / HTML stub ───────────────────────────────────────────────────

function makeSelect(id, options, selectedValue) {
    return {
        id,
        _options: options.map(o => ({ value: o.value, selected: o.value === String(selectedValue) })),
        get value() { return this._options.find(o => o.selected)?.value ?? ''; },
        set value(v) { this._options.forEach(o => { o.selected = o.value === String(v); }); },
    };
}

const elements = {
    'td-id':        { textContent: '' },
    'td-status':    { textContent: '', className: '' },
    'td-directory': { textContent: '' },
    'td-prompt':    { value: '', readOnly: false },
    'td-args':      { textContent: '' },
    'td-exit-code': { textContent: '' },
    'td-duration':  { textContent: '' },
    'td-retry-count': { textContent: '' },
    'td-result':    { textContent: '', innerHTML: '' },
    'td-priority':  { textContent: '' },
    'td-edit-row':  { style: { display: 'none' } },
    'td-edit-model':   makeSelect('td-edit-model', [
        { value: '' }, { value: 'haiku' }, { value: 'sonnet' }, { value: 'opus' },
    ], ''),
    'td-edit-effort': makeSelect('td-edit-effort', [
        { value: '' }, { value: 'low' }, { value: 'medium' }, { value: 'high' }, { value: 'max' },
    ], ''),
    'td-edit-priority': makeSelect('td-edit-priority', [
        { value: '1' }, { value: '2' }, { value: '3' },
    ], '2'),
    'td-btn-skip':   { style: { display: 'none' }, dataset: {} },
    'td-btn-retry':  { style: { display: 'none' }, dataset: {} },
    'td-btn-resume': { style: { display: 'none' }, dataset: {} },
    'td-btn-delete': { style: { display: 'none' } },
    'td-btn-duplicate': { style: { display: 'none' } },
    'td-btn-edit':   { style: { display: 'none' } },
    'td-btn-save':   { style: { display: 'none' } },
    'td-btn-cancel-edit': { style: { display: 'none' } },
    'tv-bucket':     { textContent: '' },
    'tv-created-at': { textContent: '' },
    'tv-header-id':  { textContent: '' },
    'tv-header-status': { textContent: '', className: '' },
};

global.document = {
    getElementById: id => elements[id] ?? null,
    querySelector: () => null,
    querySelectorAll: () => [],
};
global.currentTaskId = 'task_001';

// ── Re-implement the functions under test ─────────────────────────────────────

let tdOriginalPrompt = '';
let tdOriginalModel  = '';
let tdOriginalEffort = '';
let tdOriginalPriority = 2;

function escapeHtml(s) { return String(s); }
function renderText(t) { return t; }

function priorityBadge(priority) {
    const p = priority || 2;
    const labels = { 1: 'P1', 2: 'P2', 3: 'P3' };
    const cls    = { 1: 'p1', 2: 'p2', 3: 'p3' };
    return `<span class="priority-badge ${cls[p]}">${labels[p]}</span>`;
}

function renderTaskDetail(task) {
    document.getElementById('td-id').textContent = task.id;
    const statusEl = document.getElementById('td-status');
    statusEl.textContent = task.status;
    statusEl.className = `task-status ${task.status}`;
    document.getElementById('td-directory').textContent = task.directory;
    const promptEl = document.getElementById('td-prompt');
    promptEl.value = task.prompt;
    promptEl.readOnly = true;
    document.getElementById('td-args').textContent = task.args && task.args.length ? task.args.join(' ') : '—';
    document.getElementById('td-exit-code').textContent = task.exit_code !== null && task.exit_code !== undefined ? task.exit_code : '—';
    document.getElementById('td-duration').textContent = task.duration_ms !== null && task.duration_ms !== undefined ? `${(task.duration_ms / 1000).toFixed(1)}s` : '—';
    document.getElementById('td-retry-count').textContent = task.retry_count || 0;
    const resultEl = document.getElementById('td-result');
    if (task.json_output && task.json_output.result) {
        resultEl.innerHTML = renderText(task.json_output.result);
    } else {
        resultEl.textContent = '—';
    }
    tdOriginalPrompt   = task.prompt;
    tdOriginalModel    = '';
    tdOriginalEffort   = '';
    tdOriginalPriority = task.priority || 2;
    if (task.args) {
        const mi = task.args.indexOf('--model');
        if (mi >= 0 && mi + 1 < task.args.length) tdOriginalModel = task.args[mi + 1];
        const ei = task.args.indexOf('--effort');
        if (ei >= 0 && ei + 1 < task.args.length) tdOriginalEffort = task.args[ei + 1];
    }
    const priorityLabels = { 1: '1 — High', 2: '2 — Normal', 3: '3 — Low' };
    document.getElementById('td-priority').textContent = priorityLabels[tdOriginalPriority] || tdOriginalPriority;
    document.getElementById('td-edit-model').value   = tdOriginalModel;
    document.getElementById('td-edit-effort').value  = tdOriginalEffort;
    document.getElementById('td-edit-priority').value = String(tdOriginalPriority);
}

async function tdSaveTask() {
    if (!global.currentTaskId) return;
    const prompt   = document.getElementById('td-prompt').value.trim();
    const model    = document.getElementById('td-edit-model').value;
    const effort   = document.getElementById('td-edit-effort').value;
    const priority = parseInt(document.getElementById('td-edit-priority').value);
    const body = { prompt };
    if (model   !== tdOriginalModel)    body.model   = model || null;
    if (effort  !== tdOriginalEffort)   body.effort  = effort || null;
    if (priority !== tdOriginalPriority) body.priority = priority;
    await global.fetch(`/api/tasks/${global.currentTaskId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
}

// ── Test harness ─────────────────────────────────────────────────────────────

let passed = 0, failed = 0;

function assert(cond, msg) {
    if (cond) { console.log(`  ✓ ${msg}`); passed++; }
    else       { console.error(`  ✗ ${msg}`); failed++; }
}

function test(name, fn) { console.log(`\n${name}`); fn(); }

// ── Tests ────────────────────────────────────────────────────────────────────

test('priorityBadge() returns correct HTML for P1', () => {
    const html = priorityBadge(1);
    assert(html.includes('p1'), 'class contains "p1"');
    assert(html.includes('P1'), 'text contains "P1"');
    assert(html.includes('priority-badge'), 'class contains "priority-badge"');
});

test('priorityBadge() returns correct HTML for P2', () => {
    const html = priorityBadge(2);
    assert(html.includes('p2'), 'class contains "p2"');
    assert(html.includes('P2'), 'text contains "P2"');
});

test('priorityBadge() returns correct HTML for P3', () => {
    const html = priorityBadge(3);
    assert(html.includes('p3'), 'class contains "p3"');
    assert(html.includes('P3'), 'text contains "P3"');
});

test('priorityBadge() defaults to P2 when priority is missing', () => {
    const html = priorityBadge(undefined);
    assert(html.includes('p2'), 'defaults to p2');
});

test('renderTasks output contains priority badge for P1 task', () => {
    // Simulate renderTasks template literal for a single task
    const task = { id: 't1', prompt: 'fix bug', status: 'pending', priority: 1, bucket_id: 'main' };
    const html = `<span class="task-status ${task.status}">${task.status}</span>${priorityBadge(task.priority)}`;
    assert(html.includes('P1'), 'P1 badge in output');
    assert(html.includes('priority-badge p1'), 'correct css class');
});

test('renderTasks output contains priority badge for P3 task', () => {
    const task = { id: 't2', prompt: 'low priority', status: 'pending', priority: 3, bucket_id: 'main' };
    const html = `<span class="task-status ${task.status}">${task.status}</span>${priorityBadge(task.priority)}`;
    assert(html.includes('P3'), 'P3 badge in output');
    assert(html.includes('priority-badge p3'), 'correct css class');
});

test('renderTaskDetail() populates td-priority field', () => {
    const task = { id: 'task_001', prompt: 'hello', directory: '/tmp', status: 'pending',
                   priority: 1, args: [], exit_code: null, duration_ms: null, retry_count: 0, json_output: null };
    renderTaskDetail(task);
    assert(document.getElementById('td-priority').textContent === '1 — High', 'shows "1 — High"');
    assert(tdOriginalPriority === 1, 'tdOriginalPriority set to 1');
});

test('renderTaskDetail() sets td-edit-priority select to current priority', () => {
    const task = { id: 'task_001', prompt: 'hello', directory: '/tmp', status: 'pending',
                   priority: 3, args: [], exit_code: null, duration_ms: null, retry_count: 0, json_output: null };
    renderTaskDetail(task);
    assert(document.getElementById('td-edit-priority').value === '3', 'edit select pre-filled to "3"');
});

test('renderTaskDetail() defaults priority to 2 when missing', () => {
    const task = { id: 'task_001', prompt: 'hello', directory: '/tmp', status: 'pending',
                   args: [], exit_code: null, duration_ms: null, retry_count: 0, json_output: null };
    renderTaskDetail(task);
    assert(document.getElementById('td-priority').textContent === '2 — Normal', 'defaults to "2 — Normal"');
});

test('tdSaveTask() includes priority in PATCH body when changed', async () => {
    // Set up initial state: task with priority 2
    const task = { id: 'task_001', prompt: 'original', directory: '/tmp', status: 'pending',
                   priority: 2, args: [], exit_code: null, duration_ms: null, retry_count: 0, json_output: null };
    renderTaskDetail(task);

    // User changes priority to 3
    document.getElementById('td-edit-priority').value = '3';

    let capturedBody = null;
    global.fetch = async (_url, opts) => {
        capturedBody = JSON.parse(opts.body);
        return { ok: true, json: async () => ({}) };
    };

    await tdSaveTask();
    assert(capturedBody !== null, 'fetch was called');
    assert('priority' in capturedBody, 'body contains priority key');
    assert(capturedBody.priority === 3, `priority is 3 (got ${capturedBody.priority})`);
});

test('tdSaveTask() omits priority from PATCH body when unchanged', async () => {
    const task = { id: 'task_001', prompt: 'original', directory: '/tmp', status: 'pending',
                   priority: 2, args: [], exit_code: null, duration_ms: null, retry_count: 0, json_output: null };
    renderTaskDetail(task);
    // Priority stays at 2 (unchanged)

    let capturedBody = null;
    global.fetch = async (_url, opts) => {
        capturedBody = JSON.parse(opts.body);
        return { ok: true, json: async () => ({}) };
    };

    await tdSaveTask();
    assert(!('priority' in capturedBody), 'priority not sent when unchanged');
});

// ── Summary ──────────────────────────────────────────────────────────────────

console.log(`\n${'─'.repeat(40)}`);
console.log(`Results: ${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
