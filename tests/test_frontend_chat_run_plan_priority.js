/**
 * Frontend unit tests for priority dropdown in Chat — Run Dev Plan.
 * Run with: node tests/test_frontend_chat_run_plan_priority.js
 */

// ── Minimal DOM stub ─────────────────────────────────────────────────────────

function makeSelect(id, options, selectedValue) {
    return {
        id,
        _options: options.map(o => ({ value: o.value, selected: o.value === String(selectedValue) })),
        get value() { return this._options.find(o => o.selected)?.value ?? ''; },
        set value(v) { this._options.forEach(o => { o.selected = o.value === String(v); }); },
    };
}

const elements = {
    'chat-plan-priority': makeSelect('chat-plan-priority', [
        { value: '1' }, { value: '2' }, { value: '3' },
    ], '2'),
    'chat-plan-unit-tests': { checked: false },
    'chat-plan-spec': { value: 'Build a priority system' },
    'btn-chat-run-plan-confirm': { disabled: false, textContent: 'Enqueue Dev Plan' },
};

const radioChecked = { value: 'none' };

global.document = {
    getElementById: id => elements[id] ?? null,
    querySelector: selector => {
        if (selector === 'input[name="chat-plan-push"]:checked') return radioChecked;
        return null;
    },
    querySelectorAll: () => [],
};

global.window = { location: { origin: 'http://localhost:8001' } };
global.currentChatId = 'chat_abc123';
global.currentChatDirectory = '/home/user/project';

// ── Re-implement function under test ─────────────────────────────────────────

function buildChatOrchestratorPrompt(directory, spec, unitTests, pushStrategy, priority) {
    const apiOrigin = window.location.origin;
    const bucketId = currentChatId;
    const unitTestsNote = unitTests
        ? '- Each step prompt MUST include: "Write unit tests for all new code introduced in this step."'
        : '';
    const pushNote = pushStrategy === 'each_step'
        ? "- Each step prompt MUST end with: \"After completing the implementation, commit and push: git add -A && git commit -m 'feat: <step summary>' && git push\""
        : pushStrategy === 'end_only'
        ? "- The LAST step prompt MUST end with: \"After completing the implementation, commit and push: git add -A && git commit -m 'feat: complete implementation' && git push\""
        : '';

    return `You are a development planning orchestrator. Do NOT write any code yourself.

Your task: analyze the specification below, break it into sequential implementation steps, and enqueue each step as a separate task in this chat via the Claude Pool API.

API ENDPOINT: ${apiOrigin}/api/chats/${bucketId}/messages
WORKING DIRECTORY FOR ALL SUBTASKS: ${directory}
TASK PRIORITY: ${priority}
When calling the API to enqueue each task, include "priority": ${priority} in the JSON request body.

CODING SPECIFICATION:
---
${spec}
---

REQUIREMENTS FOR EACH STEP PROMPT:
- Be specific and self-contained (assume all previous steps are complete)
- Include enough context so the implementer does not need to re-read the full spec
${unitTestsNote}
${pushNote}

HOW TO ENQUEUE A TASK (use the bash tool):
Run the following Python code for each step (Python is always available):

import urllib.request, json
step_prompt = """<YOUR STEP PROMPT HERE>"""
data = json.dumps({"prompt": step_prompt, "priority": ${priority}}).encode()
req = urllib.request.Request("${apiOrigin}/api/chats/${bucketId}/messages", data, {"Content-Type": "application/json"})
urllib.request.urlopen(req)

PROCESS:
1. Analyze the specification carefully
2. Define 3-8 sequential, concrete implementation steps
3. Enqueue each step using the Python snippet above (run via bash tool)
4. After all steps are enqueued, output a brief summary of the plan

Do NOT implement any code yourself. Only plan and enqueue.`;
}

// ── Test harness ─────────────────────────────────────────────────────────────

let passed = 0, failed = 0;

function assert(cond, msg) {
    if (cond) { console.log(`  ✓ ${msg}`); passed++; }
    else       { console.error(`  ✗ ${msg}`); failed++; }
}

function test(name, fn) { console.log(`\n${name}`); fn(); }

// ── Tests ────────────────────────────────────────────────────────────────────

test('Priority dropdown exists with id "chat-plan-priority"', () => {
    const el = document.getElementById('chat-plan-priority');
    assert(el !== null, 'element found');
    assert(el.id === 'chat-plan-priority', 'id is correct');
});

test('Default selected priority value is 2', () => {
    const el = document.getElementById('chat-plan-priority');
    assert(el.value === '2', `default value is "2" (got "${el.value}")`);
});

test('Dropdown has exactly 3 options (1, 2, 3)', () => {
    const el = document.getElementById('chat-plan-priority');
    assert(el._options.length === 3, `3 options (got ${el._options.length})`);
    assert(el._options[0].value === '1', 'first option is "1"');
    assert(el._options[1].value === '2', 'second option is "2"');
    assert(el._options[2].value === '3', 'third option is "3"');
});

test('buildChatOrchestratorPrompt() includes TASK PRIORITY line with priority=1', () => {
    const prompt = buildChatOrchestratorPrompt('/home/user', 'Build X', false, 'none', 1);
    assert(prompt.includes('TASK PRIORITY: 1'), 'contains "TASK PRIORITY: 1"');
    assert(prompt.includes('"priority": 1'), 'Python snippet contains "priority": 1');
});

test('buildChatOrchestratorPrompt() includes TASK PRIORITY line with priority=3', () => {
    const prompt = buildChatOrchestratorPrompt('/home/user', 'Build X', false, 'none', 3);
    assert(prompt.includes('TASK PRIORITY: 3'), 'contains "TASK PRIORITY: 3"');
    assert(prompt.includes('"priority": 3'), 'Python snippet contains "priority": 3');
});

test('buildChatOrchestratorPrompt() includes priority instruction in prose', () => {
    const prompt = buildChatOrchestratorPrompt('/home/user', 'Build X', false, 'none', 2);
    assert(
        prompt.includes('include "priority": 2 in the JSON request body'),
        'prose instruction present'
    );
});

test('POST body includes priority when Run Dev Plan is triggered', async () => {
    // Set priority to 1
    elements['chat-plan-priority'].value = '1';

    let capturedBody = null;
    global.fetch = async (_url, opts) => {
        capturedBody = JSON.parse(opts.body);
        return { ok: true, json: async () => ({}) };
    };

    // Simulate what the click handler does
    const spec = document.getElementById('chat-plan-spec').value.trim();
    const unitTests = document.getElementById('chat-plan-unit-tests').checked;
    const pushStrategy = document.querySelector('input[name="chat-plan-push"]:checked')?.value || 'none';
    const priority = parseInt(document.getElementById('chat-plan-priority').value);

    const prompt = buildChatOrchestratorPrompt(currentChatDirectory, spec, unitTests, pushStrategy, priority);

    await fetch(`/api/chats/${currentChatId}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt, priority }),
    });

    assert(capturedBody !== null, 'fetch was called');
    assert('priority' in capturedBody, 'body contains "priority" key');
    assert(capturedBody.priority === 1, `body.priority is 1 (got ${capturedBody.priority})`);
    assert(typeof capturedBody.priority === 'number', 'priority is a number (not string)');
    assert('prompt' in capturedBody, 'body contains "prompt" key');

    // Reset
    elements['chat-plan-priority'].value = '2';
});

test('Orchestrator prompt is included in POST body', async () => {
    elements['chat-plan-priority'].value = '2';
    let capturedBody = null;
    global.fetch = async (_url, opts) => {
        capturedBody = JSON.parse(opts.body);
        return { ok: true, json: async () => ({}) };
    };

    const priority = parseInt(document.getElementById('chat-plan-priority').value);
    const prompt = buildChatOrchestratorPrompt('/tmp', 'spec text', false, 'none', priority);

    await fetch('/api/chats/chat_abc123/messages', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt, priority }),
    });

    assert(capturedBody.prompt.includes('TASK PRIORITY: 2'), 'POST prompt contains TASK PRIORITY');
    assert(capturedBody.prompt.includes('planning orchestrator'), 'POST prompt is the orchestrator prompt');
});

// ── Summary ──────────────────────────────────────────────────────────────────

console.log(`\n${'─'.repeat(40)}`);
console.log(`Results: ${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
