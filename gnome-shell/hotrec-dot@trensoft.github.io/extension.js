// SPDX-FileCopyrightText: 2026 TrenSoft
// SPDX-License-Identifier: GPL-3.0-or-later

// A dot in the top right corner of the primary monitor while Hotrec records: red and blinking
// while it records, yellow and steady while it is paused, gone otherwise. It is put in the
// Shell's top chrome with trackFullscreen off, so it stays above a fullscreen window, as the
// notifications do. A fullscreen window that mutter unredirects (direct scanout) bypasses the
// compositor, so the chrome is not drawn above it: while the dot shows, unredirect is disabled.
// Hotrec's state file is the only input; see logic.js. No timer runs while nothing records.

import St from 'gi://St';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

import {
    BLINK_MS,
    PAUSED,
    RECORDING,
    STATE_DIR,
    STATE_FILE,
    dotFor,
    parseProcStat,
    parseState,
    stateDirFor,
} from './logic.js';

const SIZE = 20;
const MARGIN_RIGHT = 16;
const MARGIN_TOP = 48; // below the 32 px top bar, so the dot never covers the bar
const DIM = 40;
const COLOURS = {[RECORDING]: '#e01b24', [PAUSED]: '#f6d32d'};

export default class HotrecDot extends Extension {
    enable() {
        this._dot = new St.Widget({
            width: SIZE,
            height: SIZE,
            reactive: false,
            can_focus: false,
            track_hover: false,
            visible: false,
        });
        Main.layoutManager.addTopChrome(this._dot, {
            affectsInputRegion: false,
            affectsStruts: false,
            trackFullscreen: false,
        });
        this._place();
        this._monitorsId = Main.layoutManager.connect('monitors-changed', () => this._place());

        this._lit = true;
        this._timer = 0;
        this._monitor = null;
        this._unredirectHeld = false;
        this._dir = stateDirFor(GLib.getenv('XDG_RUNTIME_DIR'));
        if (this._dir === null) {
            console.warn('hotrec-dot: no XDG_RUNTIME_DIR, the dot stays off');
            return;
        }
        this._file = Gio.File.new_for_path(`${this._dir}/${STATE_FILE}`);
        this._watch();
        this._evaluate();
    }

    disable() {
        this._unwatch();
        this._stopTimer();
        this._releaseUnredirect();
        if (this._monitorsId) {
            Main.layoutManager.disconnect(this._monitorsId);
            this._monitorsId = 0;
        }
        if (this._dot) {
            Main.layoutManager.removeChrome(this._dot);
            this._dot.destroy();
            this._dot = null;
        }
        this._file = null;
    }

    _place() {
        const monitor = Main.layoutManager.primaryMonitor;
        if (!monitor || !this._dot)
            return;
        this._dot.set_position(
            monitor.x + monitor.width - SIZE - MARGIN_RIGHT, monitor.y + MARGIN_TOP);
    }

    // Hotrec makes its directory when it first runs, so until it exists the runtime directory
    // is watched for it; afterwards the directory itself, for state.json.
    _watch() {
        this._unwatch();
        const dir = Gio.File.new_for_path(this._dir);
        const inDir = dir.query_exists(null);
        const target = inDir ? dir : dir.get_parent();
        try {
            this._monitor = target.monitor_directory(Gio.FileMonitorFlags.NONE, null);
        } catch (e) {
            console.warn(`hotrec-dot: cannot watch ${target.get_path()}: ${e.message}`);
            this._monitor = null;
            return;
        }
        this._monitorId = this._monitor.connect('changed', (_monitor, file) => {
            const name = file.get_basename();
            if (!inDir && name === STATE_DIR) {
                this._watch();
                this._evaluate();
            } else if (inDir && name === STATE_FILE) {
                this._evaluate();
            }
        });
    }

    _unwatch() {
        if (this._monitor) {
            this._monitor.disconnect(this._monitorId);
            this._monitor.cancel();
            this._monitor = null;
        }
    }

    _readProc(pid) {
        try {
            const [ok, bytes] = GLib.file_get_contents(`/proc/${pid}/stat`);
            return ok ? parseProcStat(new TextDecoder().decode(bytes)) : null;
        } catch (_e) {
            return null;
        }
    }

    _evaluate() {
        if (!this._dot)
            return;
        let kind = null;
        try {
            const [ok, bytes] = this._file.load_contents(null);
            const state = ok ? parseState(new TextDecoder().decode(bytes)) : null;
            kind = state ? dotFor(state, this._readProc(state.pid)) : null;
        } catch (_e) {
            kind = null; // no state file: nothing records
        }
        this._show(kind);
    }

    _show(kind) {
        if (kind === null) {
            this._stopTimer();
            this._dot.hide();
            this._releaseUnredirect();
            return;
        }
        this._holdUnredirect();
        this._dot.set_style(`background-color: ${COLOURS[kind]}; border-radius: ${SIZE / 2}px;`);
        this._dot.opacity = kind === RECORDING && !this._lit ? DIM : 255;
        this._dot.show();
        if (!this._timer) {
            this._lit = true;
            // The timer blinks the dot and checks, while a recording is on, that its process
            // is still there: a recorder that died leaves its state file behind.
            this._timer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, BLINK_MS, () => {
                this._lit = !this._lit;
                this._evaluate();
                return this._timer ? GLib.SOURCE_CONTINUE : GLib.SOURCE_REMOVE;
            });
        }
    }

    // The compositor counts the calls, so they must pair exactly: one disable when the dot
    // appears, one enable when it goes (or the extension is disabled while it shows). _show runs
    // again for every blink and colour change, hence the flag.
    _holdUnredirect() {
        if (this._unredirectHeld)
            return;
        try {
            this._unredirect(true);
        } catch (e) {
            console.warn(`hotrec-dot: cannot disable unredirect: ${e.message}`);
            return;
        }
        this._unredirectHeld = true;
    }

    // GNOME 48 and later: Meta.Compositor methods, reached as global.compositor. GNOME 47 has
    // them as functions of the Meta namespace that take the display.
    _unredirect(disable) {
        const compositor = global.compositor;
        if (typeof compositor?.disable_unredirect === 'function') {
            if (disable)
                compositor.disable_unredirect();
            else
                compositor.enable_unredirect();
        } else if (disable) {
            Meta.disable_unredirect_for_display(global.display);
        } else {
            Meta.enable_unredirect_for_display(global.display);
        }
    }

    _releaseUnredirect() {
        if (!this._unredirectHeld)
            return;
        this._unredirectHeld = false;
        try {
            this._unredirect(false);
        } catch (e) {
            console.warn(`hotrec-dot: cannot enable unredirect: ${e.message}`);
        }
    }

    _stopTimer() {
        if (this._timer) {
            GLib.Source.remove(this._timer);
            this._timer = 0;
        }
    }
}
