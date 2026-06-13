/** Sidebar view: project list with CRUD, activity badges, queue + settings links. */

import * as api from '../api.js';
import { loadProjects, getProjects, subscribe } from '../store.js';

let _container = null;

export function mount() {
    _container = document.getElementById('sidebar');
    if (!_container) return;
    _render();
    _initEventListeners();
    loadProjects().then(_render);
    subscribe('projects', _render);
}

// ── Rendering ─────────────────────────────────────────────────────────────────

function _render() {
    if (!_container) return;
    const projects = getProjects();
    _container.innerHTML = `
        <div class="sidebar-header">
            <span class="sidebar-title">Projects</span>
            <button class="btn-primary" id="sb-btn-new-project"
                style="font-size:11px;padding:4px 10px;min-height:0;"
                aria-label="New project">＋</button>
        </div>
        <div class="sidebar-project-list" role="list" aria-label="Projects">
            ${projects.length ? projects.map(_projectItem).join('') : '<div class="empty-state" style="padding:16px;font-size:0.8125rem;">No projects yet.</div>'}
        </div>
        <div class="sidebar-footer">
            <a href="#/queue" class="sidebar-footer-link" data-route="queue">
                <span aria-hidden="true">📋</span>
                <span id="sb-queue-indicator">Queue</span>
            </a>
            <a href="#/settings" class="sidebar-footer-link" data-route="settings">
                <span aria-hidden="true">⚙</span>
                <span>Settings</span>
            </a>
        </div>
    `;
    _bindProjectClicks();
    document.getElementById('sb-btn-new-project')?.addEventListener('click', _onNewProject);
}

function _projectItem(p) {
    const active = p.active_task_count > 0;
    return `
        <div class="sidebar-project-item" role="listitem" data-project-id="${p.id}"
             tabindex="0" aria-label="${_esc(p.name)}${active ? ', has active tasks' : ''}">
            ${active ? '<span class="sidebar-activity-dot" aria-hidden="true"></span>' : '<span style="width:8px;flex-shrink:0;"></span>'}
            <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${_esc(p.name)}</span>
            <button class="sb-ctx-btn" data-project-id="${p.id}" aria-label="Project options"
                style="background:none;border:none;cursor:pointer;padding:0 4px;font-size:1rem;min-height:0;width:auto;color:var(--color-text-muted);">⋯</button>
        </div>
    `;
}

// ── Event listeners ───────────────────────────────────────────────────────────

function _initEventListeners() {
    // Keyboard navigation on project items
    _container.addEventListener('keydown', e => {
        if ((e.key === 'Enter' || e.key === ' ') && e.target.classList.contains('sidebar-project-item')) {
            e.preventDefault();
            e.target.click();
        }
    });
}

function _bindProjectClicks() {
    _container.querySelectorAll('.sidebar-project-item').forEach(el => {
        el.addEventListener('click', async e => {
            if (e.target.classList.contains('sb-ctx-btn')) return; // handled below
            const id = el.dataset.projectId;
            await _navigateToProject(id);
        });
    });

    _container.querySelectorAll('.sb-ctx-btn').forEach(btn => {
        btn.addEventListener('click', e => {
            e.stopPropagation();
            _showContextMenu(btn.dataset.projectId, btn);
        });
    });
}

async function _navigateToProject(id) {
    try {
        const chatList = await api.chats.list(id);
        if (chatList.length > 0) {
            location.hash = `#/p/${id}/c/${chatList[0].id}`;
        } else {
            // Create first chat
            const chat = await api.chats.create({ project_id: id, label: 'General' });
            location.hash = `#/p/${id}/c/${chat.id}`;
        }
    } catch (err) {
        console.error('Failed to navigate to project:', err);
    }
}

async function _onNewProject() {
    const name = prompt('Project name:');
    if (!name) return;
    const directory = prompt('Directory path:');
    if (!directory) return;
    try {
        await api.projects.create({ name, directory });
        await loadProjects();
    } catch (err) {
        alert(`Failed to create project: ${err.message}`);
    }
}

function _showContextMenu(projectId, anchor) {
    // Remove any existing context menu
    document.getElementById('sb-ctx-menu')?.remove();

    const menu = document.createElement('div');
    menu.id = 'sb-ctx-menu';
    menu.setAttribute('role', 'menu');
    menu.style.cssText = `
        position:fixed; background:var(--color-surface); border:1px solid var(--color-border-dark);
        border-radius:var(--radius-md); box-shadow:var(--shadow-md); z-index:200;
        padding:4px 0; min-width:140px; font-size:0.8125rem;
    `;

    const items = [
        { label: 'Rename',  action: () => _renameProject(projectId) },
        { label: 'Archive', action: () => _archiveProject(projectId) },
        { label: 'Delete',  action: () => _deleteProject(projectId), danger: true },
    ];

    items.forEach(({ label, action, danger }) => {
        const btn = document.createElement('button');
        btn.textContent = label;
        btn.setAttribute('role', 'menuitem');
        btn.style.cssText = `
            display:block; width:100%; padding:8px 16px; background:none; border:none;
            text-align:left; cursor:pointer; color:${danger ? 'var(--color-danger)' : 'var(--color-text-primary)'};
            font-size:inherit; font-family:inherit; min-height:0;
        `;
        btn.addEventListener('click', () => { menu.remove(); action(); });
        menu.appendChild(btn);
    });

    const rect = anchor.getBoundingClientRect();
    menu.style.top  = `${rect.bottom + 4}px`;
    menu.style.left = `${rect.left}px`;
    document.body.appendChild(menu);

    const close = e => { if (!menu.contains(e.target)) { menu.remove(); document.removeEventListener('click', close); } };
    setTimeout(() => document.addEventListener('click', close), 0);
}

async function _renameProject(id) {
    const project = getProjects().find(p => p.id === id);
    const name = prompt('New name:', project?.name || '');
    if (!name) return;
    try {
        await api.projects.update(id, { name });
        await loadProjects();
    } catch (err) {
        alert(`Failed to rename: ${err.message}`);
    }
}

async function _archiveProject(id) {
    if (!confirm('Archive this project?')) return;
    try {
        await api.projects.update(id, { archived: true });
        await loadProjects();
    } catch (err) {
        alert(`Failed to archive: ${err.message}`);
    }
}

async function _deleteProject(id) {
    if (!confirm('Delete this project permanently?')) return;
    try {
        await api.projects.delete(id);
        await loadProjects();
    } catch (err) {
        alert(`Failed to delete: ${err.message}`);
    }
}

function _esc(str) {
    return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
