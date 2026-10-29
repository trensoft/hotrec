// SPDX-FileCopyrightText: 2026 TrenSoft
// SPDX-License-Identifier: GPL-3.0-or-later

// A fake desktop for extension.js: a file system with /proc and the runtime directory, a main loop
// whose timers the test advances by hand, the Shell's layout manager, and the dot widget. Needs
// fake-gnome.mjs loaded first.

class Widget {
    constructor(props) {
        Object.assign(this, {visible: true, opacity: 255, style: '', x: 0, y: 0, destroyed: false}, props);
    }
    show() { this.visible = true; }
    hide() { this.visible = false; }
    set_style(style) { this.style = style; }
    set_position(x, y) { this.x = x; this.y = y; }
    destroy() { this.destroyed = true; }
}

const W = () => globalThis.world;

const File = {
    new_for_path(path) {
        return {
            get_path: () => path,
            get_basename: () => path.slice(path.lastIndexOf('/') + 1),
            get_parent: () => File.new_for_path(path.slice(0, path.lastIndexOf('/')) || '/'),
            query_exists: () => W().dirs.has(path) || W().files.has(path),
            load_contents() {
                if (!W().files.has(path))
                    throw new Error('No such file');
                return [true, new TextEncoder().encode(W().files.get(path))];
            },
            monitor_directory() {
                const monitor = {
                    path,
                    cancelled: false,
                    handlers: new Map(),
                    nextId: 1,
                    connect(_name, fn) { this.handlers.set(this.nextId, fn); return this.nextId++; },
                    disconnect(id) { this.handlers.delete(id); },
                    cancel() { this.cancelled = true; },
                };
                W().monitors.push(monitor);
                return monitor;
            },
        };
    },
};

globalThis.fakeModules = {
    'gi://St': {Widget},
    'gi://Gio': {File, FileMonitorFlags: {NONE: 0}},
    'gi://GLib': {
        PRIORITY_DEFAULT: 0,
        SOURCE_CONTINUE: true,
        SOURCE_REMOVE: false,
        getenv: name => W().env[name] ?? null,
        file_get_contents(path) {
            if (!W().files.has(path))
                throw new Error('No such file');
            return [true, new TextEncoder().encode(W().files.get(path))];
        },
        timeout_add(_priority, milliseconds, callback) {
            const id = W().nextTimer++;
            W().timers.set(id, {milliseconds, callback});
            return id;
        },
        Source: {remove: id => W().timers.delete(id)},
    },
    'resource:///org/gnome/shell/extensions/extension.js': {Extension: class {}},
    'resource:///org/gnome/shell/ui/main.js': {
        layoutManager: {
            get primaryMonitor() { return W().primaryMonitor; },
            addTopChrome(actor, params) { W().chrome.push({actor, params}); },
            removeChrome(actor) { W().chrome = W().chrome.filter(c => c.actor !== actor); },
            connect(name, fn) { W().layoutHandlers.set(name, fn); return 7; },
            disconnect() { W().layoutHandlers.clear(); },
        },
    },
};

/** A fresh desktop for one test; the fakes above act on the latest one. */
export function makeWorld({runtimeDir = '/run/user/1000', monitor = {x: 0, y: 0, width: 1920, height: 1080}} = {}) {
    const world = {
        env: runtimeDir === null ? {} : {XDG_RUNTIME_DIR: runtimeDir},
        files: new Map(),
        dirs: new Set(['/', '/run', '/run/user', runtimeDir].filter(Boolean)),
        timers: new Map(),
        nextTimer: 1,
        monitors: [],
        chrome: [],
        layoutHandlers: new Map(),
        warnings: [],
        primaryMonitor: monitor,
        proc(pid, state, started) {
            // field 22 (index 19 after the closing parenthesis + state) is the start time
            const rest = Array.from({length: 18}, () => '0').join(' ');
            world.files.set(`/proc/${pid}/stat`, `${pid} (gpu-screen-reco) ${state} ${rest} ${started} 0 0\n`);
        },
        writeState(state) {
            world.dirs.add(`${runtimeDir}/hotrec`);
            world.files.set(`${runtimeDir}/hotrec/state.json`, JSON.stringify(state));
        },
        emit(path) {
            const dir = path.slice(0, path.lastIndexOf('/')) || '/';
            for (const m of world.monitors) {
                if (m.path === dir && !m.cancelled) {
                    for (const h of m.handlers.values())
                        h(m, {get_basename: () => path.slice(path.lastIndexOf('/') + 1)}, null, 1);
                }
            }
        },
        tick() {
            for (const [id, t] of [...world.timers]) {
                if (!world.timers.has(id))
                    continue;
                if (!t.callback())
                    world.timers.delete(id);
            }
        },
    };

    globalThis.world = world;
    return world;
}
