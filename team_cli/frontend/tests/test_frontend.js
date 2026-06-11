/**
 * Frontend unit tests for WebSocket reconnection backoff and polling behavior.
 * Run with: node team_cli/frontend/tests/test_frontend.js
 *
 * No npm/jest required — plain Node.js only.
 */

'use strict';

// ---- Minimal test harness ----

let passed = 0;
let failed = 0;

function assert(condition, message) {
    if (condition) {
        console.log(`  PASS: ${message}`);
        passed++;
    } else {
        console.error(`  FAIL: ${message}`);
        failed++;
    }
}

function assertEqual(actual, expected, message) {
    if (actual === expected) {
        console.log(`  PASS: ${message} (got ${actual})`);
        passed++;
    } else {
        console.error(`  FAIL: ${message} — expected ${expected}, got ${actual}`);
        failed++;
    }
}

function test(name, fn) {
    console.log(`\n${name}`);
    fn();
}

// ---- Module under test ----
// Extract the reconnect delay logic as a pure function so it can be tested
// without a browser environment.

/**
 * Simulates the exponential backoff reconnect logic from connectWebSocket().
 *
 * State:
 *   _wsReconnectDelay: starts at 1000, doubles on each close, capped at 30000.
 *   On open: reset to 1000.
 *
 * Returns an object with helpers that mirror the WS event handlers.
 */
function createReconnectTracker() {
    let _wsReconnectDelay = 1000;
    const scheduledDelays = [];

    function onopen() {
        _wsReconnectDelay = 1000;
    }

    function onclose() {
        scheduledDelays.push(_wsReconnectDelay);
        _wsReconnectDelay = Math.min(_wsReconnectDelay * 2, 30000);
    }

    return { onopen, onclose, scheduledDelays, getDelay: () => _wsReconnectDelay };
}

/**
 * Simulates the polling guard:
 *   if (ws && ws.readyState === WebSocket.OPEN) return;
 *
 * Returns true when the poll should be skipped (WS is connected).
 */
function shouldSkipPoll(ws) {
    const WS_OPEN = 1; // WebSocket.OPEN
    return ws !== null && ws !== undefined && ws.readyState === WS_OPEN;
}

// ---- Tests ----

test('Polling is skipped when WebSocket readyState is OPEN', () => {
    const WS_OPEN = 1;
    const WS_CONNECTING = 0;
    const WS_CLOSING = 2;
    const WS_CLOSED = 3;

    assert(shouldSkipPoll({ readyState: WS_OPEN }), 'skip when readyState === OPEN (1)');
    assert(!shouldSkipPoll({ readyState: WS_CONNECTING }), 'do not skip when CONNECTING (0)');
    assert(!shouldSkipPoll({ readyState: WS_CLOSING }), 'do not skip when CLOSING (2)');
    assert(!shouldSkipPoll({ readyState: WS_CLOSED }), 'do not skip when CLOSED (3)');
    assert(!shouldSkipPoll(null), 'do not skip when ws is null');
    assert(!shouldSkipPoll(undefined), 'do not skip when ws is undefined');
});

test('Reconnect delays follow exponential backoff sequence', () => {
    const tracker = createReconnectTracker();

    // Fire 7 close events and collect the scheduled delays
    for (let i = 0; i < 7; i++) tracker.onclose();

    // Expected: 1000, 2000, 4000, 8000, 16000, 30000, 30000
    const expected = [1000, 2000, 4000, 8000, 16000, 30000, 30000];
    const delays = tracker.scheduledDelays;

    assertEqual(delays.length, expected.length, 'collected correct number of delay entries');
    for (let i = 0; i < expected.length; i++) {
        assertEqual(delays[i], expected[i], `delay[${i}] is ${expected[i]}ms`);
    }
});

test('Reconnect delay resets to 1000ms after successful reconnect (onopen fires)', () => {
    const tracker = createReconnectTracker();

    // Simulate 4 failures — delay should have grown
    for (let i = 0; i < 4; i++) tracker.onclose();
    assert(tracker.getDelay() > 1000, 'delay grew after multiple close events');

    // Successful reconnect
    tracker.onopen();
    assertEqual(tracker.getDelay(), 1000, 'delay resets to 1000ms after onopen');

    // The next close should schedule 1000ms again (not the previous large value)
    tracker.onclose();
    assertEqual(tracker.scheduledDelays[tracker.scheduledDelays.length - 1], 1000,
        'first close after reset schedules 1000ms delay');
});

test('Backoff is capped at 30000ms (30s max)', () => {
    const tracker = createReconnectTracker();

    // Fire many close events
    for (let i = 0; i < 20; i++) tracker.onclose();

    const delays = tracker.scheduledDelays;
    const allCapped = delays.slice(5).every(d => d === 30000);
    assert(allCapped, 'all delays after 5th close are capped at 30000ms');
});

// ---- Summary ----

console.log(`\n--- Results: ${passed} passed, ${failed} failed ---`);
if (failed > 0) {
    process.exit(1);
}
