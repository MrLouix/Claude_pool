/** Central state store: projects, chats, messages, tasks, settings. Pub/sub pattern. */

import * as api from './api.js';

const _state = {
    projects:    [],
    chats:       {},   // keyed by projectId → []
    messages:    {},   // keyed by chatId    → []
    tasks:       [],
    poolStatus:  null,
    settings:    { cliCommands: [] },
};

const _listeners = new Map(); // topic → Set<fn>

export function subscribe(topic, fn) {
    if (!_listeners.has(topic)) _listeners.set(topic, new Set());
    _listeners.get(topic).add(fn);
    return () => _listeners.get(topic).delete(fn);
}

function _notify(topic, data) {
    (_listeners.get(topic) || new Set()).forEach(fn => fn(data));
}

// ── Selectors ─────────────────────────────────────────────────────────────────
export const getProjects    = ()         => _state.projects;
export const getChats       = (pid)      => _state.chats[pid]      || [];
export const getMessages    = (cid)      => _state.messages[cid]   || [];
export const getTasks       = ()         => _state.tasks;
export const getPoolStatus  = ()         => _state.poolStatus;
export const getCliCommands = ()         => _state.settings.cliCommands;

// ── Loaders ───────────────────────────────────────────────────────────────────
export async function loadProjects() {
    const data = await api.projects.list();
    _state.projects = data;
    _notify('projects', _state.projects);
    return data;
}

export async function loadChats(projectId) {
    const data = await api.chats.list(projectId);
    _state.chats[projectId] = data;
    _notify('chats', { projectId, chats: data });
    return data;
}

export async function loadMessages(chatId) {
    const data = await api.messages.list(chatId);
    _state.messages[chatId] = data;
    _notify('messages', { chatId, messages: data });
    return data;
}

export async function loadTasks() {
    const data = await api.tasks.list();
    _state.tasks = data;
    _notify('tasks', _state.tasks);
    return data;
}

export async function loadCliCommands() {
    const data = await api.cliCommands.list();
    _state.settings.cliCommands = data;
    _notify('settings', _state.settings);
    return data;
}

// ── WebSocket event handlers ──────────────────────────────────────────────────
export function applyWsEvent(msg) {
    switch (msg.event) {
        case 'pool_status':
            _state.poolStatus = msg.data;
            _notify('pool_status', msg.data);
            break;
        case 'task_updated': {
            const task = _state.tasks.find(t => t.id === msg.task?.id);
            if (task) Object.assign(task, msg.task);
            else if (msg.task) _state.tasks.push(msg.task);
            _notify('tasks', _state.tasks);
            break;
        }
        case 'message_created':
            _notify('message_created', msg.data);
            break;
        default:
            _notify('ws_event', msg);
    }
}
