// SPDX-FileCopyrightText: 2026 TrenSoft
// SPDX-License-Identifier: GPL-3.0-or-later

import test from 'node:test';
import assert from 'node:assert/strict';

import {PAUSED, RECORDING, dotFor, parseProcStat, parseState, stateDirFor}
    from '../../gnome-shell/hotrec-dot@trensoft.github.io/logic.js';

const STAT = (state, started) =>
    `4242 (gpu-screen-reco) ${state} ${Array.from({length: 18}, () => '1').join(' ')} ${started} 9 9\n`;

test('the state directory follows the runtime directory, as Hotrec does', () => {
    assert.equal(stateDirFor('/run/user/1000'), '/run/user/1000/hotrec');
    assert.equal(stateDirFor('/run/user/1000/'), '/run/user/1000/hotrec');
    assert.equal(stateDirFor('relative'), null);
    assert.equal(stateDirFor(''), null);
    assert.equal(stateDirFor(null), null);
});

test('parseState reads the fields Hotrec writes', () => {
    const text = JSON.stringify({pid: 7, started: 99, mode: 'video', file: '/f', paused: false});
    assert.deepEqual(parseState(text), {pid: 7, started: 99, mode: 'video', paused: false});
    assert.equal(parseState(JSON.stringify({pid: 7, started: 99, mode: 'audio', paused: true})).paused, true);
});

test('a missing paused field means not paused, and only true means paused', () => {
    assert.equal(parseState('{"pid":7,"started":1,"mode":"video"}').paused, false);
    assert.equal(parseState('{"pid":7,"started":1,"mode":"video","paused":"yes"}').paused, false);
});

for (const [name, text] of [
    ['not json', 'oops'],
    ['an empty file', ''],
    ['null', 'null'],
    ['a list', '[1]'],
    ['no pid', '{"started":1,"mode":"video"}'],
    ['a pid of zero', '{"pid":0,"started":1,"mode":"video"}'],
    ['a text pid', '{"pid":"7","started":1,"mode":"video"}'],
    ['no start time', '{"pid":7,"mode":"video"}'],
    ['no mode', '{"pid":7,"started":1}'],
]) {
    test(`parseState refuses ${name}`, () => {
        assert.equal(parseState(text), null);
    });
}

test('parseProcStat takes the state and the start time after the last parenthesis', () => {
    assert.deepEqual(parseProcStat(STAT('S', 555)), {state: 'S', started: 555});
    // a process name may hold spaces and parentheses
    assert.deepEqual(parseProcStat(STAT('S', 555).replace('gpu-screen-reco', 'a) (b c')), {state: 'S', started: 555});
});

for (const [name, text] of [
    ['null', null],
    ['an empty file', ''],
    ['no parentheses', '4242 S 1 2 3'],
    ['too few fields', '4242 (x) S 1 2 3'],
    ['one field short of the start time', `4242 (x) S ${Array.from({length: 18}, () => '1').join(' ')}`],
    ['a start time that is no number', STAT('S', 'abc')],
]) {
    test(`parseProcStat refuses ${name}`, () => {
        assert.equal(parseProcStat(text), null);
    });
}

test('the dot is red for the recording process, yellow while paused', () => {
    const state = {pid: 4242, started: 555, mode: 'video', paused: false};
    assert.equal(dotFor(state, {state: 'S', started: 555}), RECORDING);
    assert.equal(dotFor({...state, paused: true}, {state: 'T', started: 555}), PAUSED);
});

test('no dot without a state, without the process, for a reused pid or a dead one', () => {
    const state = {pid: 4242, started: 555, mode: 'video', paused: false};
    assert.equal(dotFor(null, {state: 'S', started: 555}), null);
    assert.equal(dotFor(state, null), null);
    assert.equal(dotFor(state, {state: 'S', started: 556}), null); // the pid now belongs to another process
    assert.equal(dotFor(state, {state: 'Z', started: 555}), null);
    assert.equal(dotFor(state, {state: 'X', started: 555}), null);
});
