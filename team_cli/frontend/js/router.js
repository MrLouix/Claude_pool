/** Hash-based SPA router: mounts views based on URL hash. */

import { connect as wsConnect } from './ws.js';
import { applyWsEvent } from './store.js';
import { mount as mountSidebar } from './views/sidebar.js';
import { mount as mountChat }    from './views/chat.js';
import { mount as mountThread }  from './views/thread.js';
import { mount as mountQueue }   from './views/queue.js';
import { mount as mountSettings } from './views/settings.js';

// Route table: pattern → { view, params extractor }
const ROUTES = [
    { re: /^#\/p\/([^/]+)\/c\/([^/]+)$/, view: 'chat',     params: m => ({ projectId: m[1], chatId: m[2] }) },
    { re: /^#\/p\/([^/]+)$/,              view: 'project',  params: m => ({ projectId: m[1] }) },
    { re: /^#\/settings$/,                view: 'settings', params: () => ({}) },
    { re: /^#\/queue$/,                   view: 'queue',    params: () => ({}) },
];

let _current = null;

function _resolve(hash) {
    if (!hash || hash === '#' || hash === '#/') return { view: 'home', params: {} };
    for (const { re, view, params } of ROUTES) {
        const m = hash.match(re);
        if (m) return { view, params: params(m) };
    }
    return { view: 'home', params: {} };
}

async function _navigate() {
    const hash = location.hash || '#/';
    const { view, params } = _resolve(hash);
    if (_current?.view === view && JSON.stringify(_current.params) === JSON.stringify(params)) return;
    _current = { view, params };

    // Update bottom-nav active state
    document.querySelectorAll('.bottom-nav-item').forEach(el => {
        el.classList.toggle('active',
            (view === 'settings' && el.dataset.route === 'settings') ||
            (view === 'queue'    && el.dataset.route === 'queue')    ||
            (['home','project','chat'].includes(view) && el.dataset.route === 'chats')
        );
    });

    // Mount the appropriate view
    switch (view) {
        case 'chat':     await mountChat(params);     break;
        case 'settings': await mountSettings(params); break;
        case 'queue':    await mountQueue(params);    break;
        default:         break;
    }
}

// Boot
document.addEventListener('DOMContentLoaded', () => {
    // WebSocket
    wsConnect();
    window.addEventListener('pool:pool_status',    ev => applyWsEvent(ev.detail));
    window.addEventListener('pool:task_updated',   ev => applyWsEvent({ event: 'task_updated', task: ev.detail.task }));
    window.addEventListener('pool:message_created',ev => applyWsEvent({ event: 'message_created', data: ev.detail }));

    // Mount persistent sidebar
    mountSidebar();

    // Routing
    window.addEventListener('hashchange', _navigate);
    _navigate();
});
