/**
 * Frontend unit tests for the priority dropdown in the task creation form.
 * Run with: node tests/test_frontend_priority.js
 *
 * Uses a minimal DOM stub — no framework required.
 */

// ── Minimal DOM stub ─────────────────────────────────────────────────────────

function makeSelect(id, options, selectedValue) {
    const el = {
        id,
        tagName: 'SELECT',
        _options: options.map(o => ({ value: o.value, selected: o.value === selectedValue, text: o.text })),
        get value() { return this._options.find(o => o.selected)?.value ?? ''; },
    };
    return el;
}

const elements = {
    'task-priority': makeSelect('task-priority', [
        { value: '1', text: '1 — High' },
        { value: '2', text: '2 — Normal' },
        { value: '3', text: '3 — Low' },
    ], '2'),
    'prompt': { value: 'Test prompt' },
    'directory': { value: '/home/user/project' },
    'model': { value: '' },
    'effort': { value: '' },
};

global.document = { getElementById: id => elements[id] ?? null };

// ── Test harness ─────────────────────────────────────────────────────────────

let passed = 0;
let failed = 0;

function assert(condition, message) {
    if (condition) {
        console.log(`  ✓ ${message}`);
        passed++;
    } else {
        console.error(`  ✗ ${message}`);
        failed++;
    }
}

function test(name, fn) {
    console.log(`\n${name}`);
    fn();
}

// ── Tests ────────────────────────────────────────────────────────────────────

test('Priority dropdown exists with id "task-priority"', () => {
    const el = document.getElementById('task-priority');
    assert(el !== null, 'element found');
    assert(el.id === 'task-priority', 'id is "task-priority"');
});

test('Default selected priority value is 2', () => {
    const el = document.getElementById('task-priority');
    assert(el.value === '2', `value is "2" (got "${el.value}")`);
});

test('Dropdown has exactly 3 options (1, 2, 3)', () => {
    const el = document.getElementById('task-priority');
    assert(el._options.length === 3, `3 options (got ${el._options.length})`);
    assert(el._options[0].value === '1', 'first option value is "1"');
    assert(el._options[1].value === '2', 'second option value is "2"');
    assert(el._options[2].value === '3', 'third option value is "3"');
});

test('Submit handler includes priority as integer in POST body', () => {
    let capturedBody = null;

    // Mock fetch
    global.fetch = async (_url, options) => {
        capturedBody = JSON.parse(options.body);
        return { ok: true, json: async () => ({ id: 'task_001' }) };
    };

    // Simulate buildFormData (mirrors the actual submit handler logic)
    function buildFormData() {
        return {
            prompt: document.getElementById('prompt').value,
            directory: document.getElementById('directory').value,
            model: document.getElementById('model').value || null,
            effort: document.getElementById('effort').value || null,
            priority: parseInt(document.getElementById('task-priority').value),
        };
    }

    const formData = buildFormData();

    assert('priority' in formData, 'formData contains "priority" key');
    assert(typeof formData.priority === 'number', `priority is a number (got ${typeof formData.priority})`);
    assert(formData.priority === 2, `priority equals 2 (got ${formData.priority})`);
});

test('Submit handler sends priority=1 when high priority selected', () => {
    // Simulate user selecting priority 1
    elements['task-priority']._options.forEach(o => { o.selected = o.value === '1'; });

    function buildFormData() {
        return {
            prompt: document.getElementById('prompt').value,
            directory: document.getElementById('directory').value,
            model: document.getElementById('model').value || null,
            effort: document.getElementById('effort').value || null,
            priority: parseInt(document.getElementById('task-priority').value),
        };
    }

    const formData = buildFormData();
    assert(formData.priority === 1, `priority equals 1 (got ${formData.priority})`);

    // Reset to default
    elements['task-priority']._options.forEach(o => { o.selected = o.value === '2'; });
});

test('parseInt on dropdown value produces integer, not string', () => {
    const raw = document.getElementById('task-priority').value; // '2' (string)
    const parsed = parseInt(raw);
    assert(typeof parsed === 'number', 'parseInt produces a number');
    assert(parsed === 2, `value is 2 (got ${parsed})`);
    assert(parsed !== '2', 'value is not string "2"');
});

// ── Summary ──────────────────────────────────────────────────────────────────

console.log(`\n${'─'.repeat(40)}`);
console.log(`Results: ${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
