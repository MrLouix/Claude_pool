/** WebSocket client: connects to /ws/events, reconnects on disconnect, emits custom DOM events. */

const WS_RECONNECT_BASE_MS = 1000;
const WS_RECONNECT_MAX_MS  = 30000;

let _ws = null;
let _reconnectDelay = WS_RECONNECT_BASE_MS;
let _reconnectTimer = null;

function _getUrl() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${proto}//${location.host}/ws/events`;
}

function _emit(type, detail) {
    window.dispatchEvent(new CustomEvent(`pool:${type}`, { detail }));
}

function _connect() {
    if (_ws && _ws.readyState <= WebSocket.OPEN) return;

    _ws = new WebSocket(_getUrl());

    _ws.addEventListener('open', () => {
        _reconnectDelay = WS_RECONNECT_BASE_MS;
        _emit('connected', {});

        // Keepalive ping every 25s
        const ping = setInterval(() => {
            if (_ws && _ws.readyState === WebSocket.OPEN) {
                _ws.send('ping');
            } else {
                clearInterval(ping);
            }
        }, 25000);
    });

    _ws.addEventListener('message', (ev) => {
        if (ev.data === 'pong') return;
        try {
            const msg = JSON.parse(ev.data);
            _emit(msg.event || 'message', msg);
        } catch {
            _emit('raw', { data: ev.data });
        }
    });

    _ws.addEventListener('close', () => {
        _emit('disconnected', {});
        _scheduleReconnect();
    });

    _ws.addEventListener('error', () => {
        _ws.close();
    });
}

function _scheduleReconnect() {
    if (_reconnectTimer) return;
    _reconnectTimer = setTimeout(() => {
        _reconnectTimer = null;
        _reconnectDelay = Math.min(_reconnectDelay * 2, WS_RECONNECT_MAX_MS);
        _connect();
    }, _reconnectDelay);
}

/** Start the WebSocket connection. Call once on page load. */
export function connect() {
    _connect();
}

/** Manually disconnect (e.g. for testing). */
export function disconnect() {
    if (_reconnectTimer) { clearTimeout(_reconnectTimer); _reconnectTimer = null; }
    if (_ws) { _ws.close(); _ws = null; }
}
