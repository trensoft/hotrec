// SPDX-FileCopyrightText: 2026 TrenSoft
// SPDX-License-Identifier: GPL-3.0-or-later

// extension.js against a fake desktop (fake-gnome.mjs, world.mjs): run with
// `node --import ./tests/js/fake-gnome.mjs --test tests/js/`.
import test, {afterEach} from 'node:test';
import assert from 'node:assert/strict';

import {makeWorld} from './world.mjs';

makeWorld();
const {default: HotrecDot} = await import('../../gnome-shell/hotrec-dot@trensoft.github.io/extension.js');

const RUN = '/run/user/1000';
const STATE = `${RUN}/hotrec/state.json`;
const recording = (extra = {}) => ({pid: 4242, started: 555, mode: 'video', file: '/f.mkv', paused: false, ...extra});

const started = [];

function start(setup = () => {}, options) {
    const world = makeWorld(options);
    setup(world);
    const extension = new HotrecDot();
    extension.enable();
    started.push({world, extension});
    return {world, extension, dot: world.chrome[0]?.actor};
}

// Whatever a test did, once the extension is disabled the compositor's unredirect count is 0:
// every disable was matched by one enable, and none was enabled twice.
afterEach(() => {
    for (const {world, extension} of started.splice(0)) {
        extension.disable();
        assert.equal(world.unredirect.depth, 0, `unredirect left disabled: ${world.unredirect.calls}`);
        assert.equal(world.unredirect.underflows, 0, `unredirect enabled once too often: ${world.unredirect.calls}`);
        assert.equal(world.unredirect.disable, world.unredirect.enable);
    }
});

const showing = w => {
    w.proc(4242, 'S', 555);
    w.writeState(recording());
};

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

// -- unredirect: a fullscreen window that is unredirected (direct scanout) covers the top chrome ----

// GNOME 48 and later have global.compositor.disable_unredirect(); GNOME 47 has the same on the Meta
// namespace, taking the display. Both are run through the same cases.
for (const [api, via] of [['compositor', 'GNOME 48/49: global.compositor'], ['display', 'GNOME 47: Meta.*_for_display']]) {
    const calls = (world, ...ops) => ops.map(op => `${api}:${op}`).join() === world.unredirect.calls.join();

    test(`unredirect (${via}): the dot appearing disables it once`, () => {
        const {world, dot} = start(showing, {api});
        assert.equal(dot.visible, true);
        assert.deepEqual(world.unredirect.calls, [`${api}:disable`]);
        assert.equal(world.unredirect.depth, 1);
    });

    test(`unredirect (${via}): no dot, no call`, () => {
        const {world} = start(() => {}, {api});
        assert.deepEqual(world.unredirect.calls, []);
    });

    test(`unredirect (${via}): blinking, pausing, resuming and a repeated state change call nothing more`, () => {
        const {world} = start(showing, {api});
        for (let i = 0; i < 6; i++)
            world.tick(); // blink
        world.writeState(recording({paused: true}));
        world.emit(STATE); // colour change
        world.emit(STATE); // the same state again
        world.writeState(recording());
        world.emit(STATE); // blinking again
        world.tick();
        assert.equal(calls(world, 'disable'), true, world.unredirect.calls.join());
        assert.equal(world.unredirect.depth, 1);
    });

    test(`unredirect (${via}): the dot going away enables it once, and only once`, () => {
        const {world, dot} = start(showing, {api});
        world.files.delete(STATE);
        world.emit(STATE);
        assert.equal(dot.visible, false);
        assert.equal(world.unredirect.depth, 0);
        world.emit(STATE); // nothing records: still nothing to give back
        world.tick();
        assert.equal(calls(world, 'disable', 'enable'), true, world.unredirect.calls.join());
    });

    test(`unredirect (${via}): a recorder that died takes the dot and the hold away at the next tick`, () => {
        const {world} = start(showing, {api});
        world.files.delete('/proc/4242/stat');
        world.tick();
        assert.equal(calls(world, 'disable', 'enable'), true, world.unredirect.calls.join());
    });

    test(`unredirect (${via}): every appearance is paired with its own disappearance`, () => {
        const {world} = start(w => w.dirs.add(`${RUN}/hotrec`), {api});
        for (let i = 0; i < 3; i++) {
            world.proc(4242, 'S', 555);
            world.writeState(recording());
            world.emit(STATE);
            assert.equal(world.unredirect.depth, 1);
            world.files.delete(STATE);
            world.emit(STATE);
            assert.equal(world.unredirect.depth, 0);
        }
        assert.equal(world.unredirect.disable, 3);
        assert.equal(world.unredirect.enable, 3);
    });

    test(`unredirect (${via}): disabling the extension while the dot shows enables it`, () => {
        const {world, extension} = start(showing, {api});
        extension.disable();
        assert.equal(calls(world, 'disable', 'enable'), true, world.unredirect.calls.join());
        assert.equal(world.unredirect.depth, 0);
        extension.disable(); // a second disable gives nothing back again
        assert.equal(world.unredirect.enable, 1);
    });

    test(`unredirect (${via}): disabling the extension while the dot is hidden calls nothing`, () => {
        const {world, extension} = start(() => {}, {api});
        extension.disable();
        assert.deepEqual(world.unredirect.calls, []);
    });

    test(`unredirect (${via}): enable after disable holds it again, once`, () => {
        const {world, extension} = start(showing, {api});
        extension.disable();
        extension.enable();
        assert.equal(calls(world, 'disable', 'enable', 'disable'), true, world.unredirect.calls.join());
        assert.equal(world.unredirect.depth, 1);
    });
}

test('unredirect: if the call fails the dot still shows and nothing is given back that was not taken', () => {
    const {world, dot, extension} = start(showing, {unredirectThrows: true});
    assert.equal(dot.visible, true);
    world.tick(); // tries again at every blink: nothing was taken
    extension.disable();
    assert.equal(world.unredirect.enable, 0);
});
