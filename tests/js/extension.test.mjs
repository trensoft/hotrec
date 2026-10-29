// SPDX-FileCopyrightText: 2026 TrenSoft
// SPDX-License-Identifier: GPL-3.0-or-later

// extension.js against a fake desktop (fake-gnome.mjs, world.mjs): run with
// `node --import ./tests/js/fake-gnome.mjs --test tests/js/`.
import test from 'node:test';
import assert from 'node:assert/strict';

import {makeWorld} from './world.mjs';

makeWorld();
const {default: HotrecDot} = await import('../../gnome-shell/hotrec-dot@trensoft.github.io/extension.js');

const RUN = '/run/user/1000';
const STATE = `${RUN}/hotrec/state.json`;
const recording = (extra = {}) => ({pid: 4242, started: 555, mode: 'video', file: '/f.mkv', paused: false, ...extra});

function start(setup = () => {}, options) {
    const world = makeWorld(options);
    setup(world);
    const extension = new HotrecDot();
    extension.enable();
    return {world, extension, dot: world.chrome[0]?.actor};
}

test('the dot is put above fullscreen windows and never takes input', () => {
    const {world} = start();
    assert.equal(world.chrome.length, 1);
    assert.deepEqual(world.chrome[0].params, {affectsInputRegion: false, affectsStruts: false, trackFullscreen: false});
    const dot = world.chrome[0].actor;
    assert.equal(dot.reactive, false);
    assert.equal(dot.can_focus, false);
});

test('the dot sits in the top right corner of the primary monitor, below the bar', () => {
    const {dot} = start(() => {}, {monitor: {x: 100, y: 50, width: 1000, height: 800}});
    assert.deepEqual([dot.x, dot.y], [100 + 1000 - 20 - 16, 50 + 48]);
});

test('nothing records: the dot is hidden and no timer runs', () => {
    const {world, dot} = start();
    assert.equal(dot.visible, false);
    assert.equal(world.timers.size, 0);
});

test('a recording that is already running at login shows the red dot at once', () => {
    const {world, dot} = start(w => {
        w.proc(4242, 'S', 555);
        w.writeState(recording());
    });
    assert.equal(dot.visible, true);
    assert.match(dot.style, /#e01b24/);
    assert.equal(world.timers.size, 1);
});

test('the red dot blinks every half second and the timer is the only one', () => {
    const {world, dot} = start(w => {
        w.proc(4242, 'S', 555);
        w.writeState(recording());
    });
    assert.equal([...world.timers.values()][0].milliseconds, 500);
    const seen = [];
    for (let i = 0; i < 6; i++) {
        world.tick();
        seen.push(dot.opacity);
    }
    assert.deepEqual(seen, [40, 255, 40, 255, 40, 255]);
    assert.equal(world.timers.size, 1);
});

test('a recording that starts later: the state file appearing turns the dot on, its removal off', () => {
    const {world, dot} = start(w => w.dirs.add(`${RUN}/hotrec`)); // Hotrec has run before
    world.proc(4242, 'S', 555);
    world.writeState(recording());
    world.emit(STATE);
    assert.equal(dot.visible, true);
    assert.equal(world.timers.size, 1);
    world.files.delete(STATE);
    world.emit(STATE);
    assert.equal(dot.visible, false);
    assert.equal(world.timers.size, 0);
});

test('the runtime directory is watched until Hotrec makes its own, then that one', () => {
    const {world, dot} = start();
    assert.equal(world.monitors.length, 1);
    assert.equal(world.monitors[0].path, RUN);
    world.proc(4242, 'S', 555);
    world.writeState(recording()); // makes the directory
    world.emit(`${RUN}/hotrec`);
    assert.equal(dot.visible, true); // a state that is there when the directory shows up counts
    assert.equal(world.monitors.length, 2);
    assert.equal(world.monitors[0].cancelled, true);
    assert.equal(world.monitors[1].path, `${RUN}/hotrec`);
    world.files.delete(STATE);
    world.emit(STATE);
    assert.equal(dot.visible, false);
});

test('other files in the directory change nothing', () => {
    const {world, dot} = start(w => {
        w.proc(4242, 'S', 555);
        w.writeState(recording());
    });
    world.files.delete(STATE);
    world.files.set(`${RUN}/hotrec/recorder.log`, 'x');
    world.emit(`${RUN}/hotrec/recorder.log`);
    assert.equal(dot.visible, true); // only state.json is read
});

test('pausing makes the dot yellow and steady, resuming makes it blink again', () => {
    const {world, dot} = start(w => {
        w.proc(4242, 'S', 555);
        w.writeState(recording());
    });
    world.tick(); // dim half
    world.writeState(recording({paused: true}));
    world.emit(STATE);
    assert.match(dot.style, /#f6d32d/);
    assert.equal(dot.opacity, 255);
    world.tick();
    world.tick();
    assert.equal(dot.opacity, 255); // steady
    world.writeState(recording());
    world.emit(STATE);
    assert.match(dot.style, /#e01b24/);
});

test('a sound recording shows the dot too', () => {
    const {dot} = start(w => {
        w.proc(4242, 'S', 555);
        w.writeState(recording({mode: 'audio', file: '/f.mp3'}));
    });
    assert.equal(dot.visible, true);
});

test('a recorder that died leaves its state file: the next tick takes the dot away', () => {
    const {world, dot} = start(w => {
        w.proc(4242, 'S', 555);
        w.writeState(recording());
    });
    world.files.delete('/proc/4242/stat');
    world.tick();
    assert.equal(dot.visible, false);
    assert.equal(world.timers.size, 0);
});

test('a state file of a process that is gone before login shows nothing', () => {
    const {world, dot} = start(w => w.writeState(recording()));
    assert.equal(dot.visible, false);
    assert.equal(world.timers.size, 0);
});

test('the pid reused by another process is not the recording', () => {
    const {dot} = start(w => {
        w.proc(4242, 'S', 99999);
        w.writeState(recording());
    });
    assert.equal(dot.visible, false);
});

test('a half-written or foreign state file shows nothing and breaks nothing', () => {
    const {world, dot} = start(w => {
        w.proc(4242, 'S', 555);
        w.dirs.add(`${RUN}/hotrec`);
        w.files.set(STATE, '{"pid": 4242, "sta');
    });
    assert.equal(dot.visible, false);
    world.writeState(recording());
    world.emit(STATE);
    assert.equal(dot.visible, true);
});

test('without a runtime directory the dot stays off', () => {
    const {world, dot} = start(() => {}, {runtimeDir: null});
    assert.equal(dot.visible, false);
    assert.equal(world.monitors.length, 0);
});

test('the dot follows the primary monitor when the monitors change', () => {
    const {world, dot} = start();
    world.primaryMonitor = {x: 0, y: 0, width: 1280, height: 720};
    world.layoutHandlers.get('monitors-changed')();
    assert.deepEqual([dot.x, dot.y], [1280 - 20 - 16, 48]);
});

test('disabling removes the dot, the timer and the watch', () => {
    const {world, extension, dot} = start(w => {
        w.proc(4242, 'S', 555);
        w.writeState(recording());
    });
    extension.disable();
    assert.equal(world.chrome.length, 0);
    assert.equal(dot.destroyed, true);
    assert.equal(world.timers.size, 0);
    assert.equal(world.monitors.every(m => m.cancelled), true);
    assert.equal(world.layoutHandlers.size, 0);
});

test('enable after disable works again', () => {
    const {world, extension} = start(w => {
        w.proc(4242, 'S', 555);
        w.writeState(recording());
    });
    extension.disable();
    extension.enable();
    assert.equal(world.chrome.length, 1);
    assert.equal(world.chrome[0].actor.visible, true);
});
