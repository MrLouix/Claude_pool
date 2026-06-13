/** Fetch wrapper for all Claude Pool REST endpoints. */

const BASE = '';

async function _fetch(path, opts = {}) {
    const res = await fetch(BASE + path, {
        headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
        ...opts,
    });
    if (!res.ok) {
        const text = await res.text().catch(() => '');
        throw Object.assign(new Error(`HTTP ${res.status}: ${text}`), { status: res.status });
    }
    const ct = res.headers.get('content-type') || '';
    return ct.includes('application/json') ? res.json() : res.text();
}

// ── Projects ──────────────────────────────────────────────────────────────────
export const projects = {
    list:    ()        => _fetch('/api/projects'),
    get:     (id)      => _fetch(`/api/projects/${id}`),
    create:  (body)    => _fetch('/api/projects',      { method: 'POST', body: JSON.stringify(body) }),
    update:  (id, body)=> _fetch(`/api/projects/${id}`,{ method: 'PATCH', body: JSON.stringify(body) }),
    delete:  (id)      => _fetch(`/api/projects/${id}`,{ method: 'DELETE' }),
};

// ── Chats ─────────────────────────────────────────────────────────────────────
export const chats = {
    list:            (projectId)       => _fetch(`/api/projects/${projectId}/chats`),
    get:             (id)              => _fetch(`/api/chats/${id}`),
    create:          (body)            => _fetch('/api/chats',                         { method: 'POST',   body: JSON.stringify(body) }),
    createInProject: (projectId, body) => _fetch(`/api/projects/${projectId}/chats`,  { method: 'POST',   body: JSON.stringify(body) }),
    update:          (id, body)        => _fetch(`/api/chats/${id}`,                  { method: 'PATCH',  body: JSON.stringify(body) }),
    delete:          (id)              => _fetch(`/api/chats/${id}`,                  { method: 'DELETE' }),
};

// ── Messages ──────────────────────────────────────────────────────────────────
export const messages = {
    list:     (chatId)              => _fetch(`/api/chats/${chatId}/messages`),
    listPage: (chatId, params = {}) => {
        const qs = new URLSearchParams({ paginate: 'true', ...params }).toString();
        return _fetch(`/api/chats/${chatId}/messages?${qs}`);
    },
    create:   (chatId, body)        => _fetch(`/api/chats/${chatId}/messages`,  { method: 'POST',   body: JSON.stringify(body) }),
    delete:   (id)                  => _fetch(`/api/messages/${id}`,            { method: 'DELETE' }),
};

// ── Tasks ─────────────────────────────────────────────────────────────────────
export const tasks = {
    list:    ()           => _fetch('/api/tasks'),
    get:     (id)         => _fetch(`/api/tasks/${id}`),
    create:  (body)       => _fetch('/api/tasks',      { method: 'POST', body: JSON.stringify(body) }),
    update:  (id, body)   => _fetch(`/api/tasks/${id}`,{ method: 'PATCH', body: JSON.stringify(body) }),
    delete:  (id)         => _fetch(`/api/tasks/${id}`,{ method: 'DELETE' }),
    skip:    (id)         => _fetch(`/api/tasks/${id}/skip`,  { method: 'POST' }),
    retry:   (id)         => _fetch(`/api/tasks/${id}/retry`, { method: 'POST' }),
};

// ── Settings: CLI commands ────────────────────────────────────────────────────
export const cliCommands = {
    list:    ()       => _fetch('/api/settings/cli-commands'),
    update:  (body)   => _fetch('/api/settings/cli-commands', { method: 'PUT', body: JSON.stringify(body) }),
    test:    (id)     => _fetch('/api/settings/cli-commands/test', { method: 'POST', body: JSON.stringify({ id }) }),
};

// ── Pool ──────────────────────────────────────────────────────────────────────
export const pool = {
    status:  ()       => _fetch('/api/pool'),
    suspend: ()       => _fetch('/api/pool/suspend',  { method: 'POST' }),
    resume:  ()       => _fetch('/api/pool/resume',   { method: 'POST' }),
};
