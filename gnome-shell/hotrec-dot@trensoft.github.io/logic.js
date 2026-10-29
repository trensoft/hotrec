// SPDX-FileCopyrightText: 2026 TrenSoft
// SPDX-License-Identifier: GPL-3.0-or-later

// The decisions of the Hotrec recording dot, without any GNOME API, so they can be tested
// with plain node. The state file is the one Hotrec itself keeps (hotrec/recorder.py, class State
// and Recorder.read_state): `{"pid", "started", "mode", "file", "paused"}` in
// $XDG_RUNTIME_DIR/hotrec/state.json, with `started` the start time of the pid from
// /proc/<pid>/stat (field 22, clock ticks since boot).

export const STATE_FILE = 'state.json';
export const STATE_DIR = 'hotrec';
export const BLINK_MS = 500;

// 'recording' = the red blinking dot, 'paused' = the yellow one that does not blink, null = no dot.
export const RECORDING = 'recording';
export const PAUSED = 'paused';

/**
 * The directory Hotrec keeps its state in, or null when there is no usable runtime directory
 * (Hotrec then falls back to /tmp/hotrec-<uid>; a Shell session always has XDG_RUNTIME_DIR).
 */
export function stateDirFor(runtimeDir) {
    if (typeof runtimeDir !== 'string' || !runtimeDir.startsWith('/'))
        return null;
    return `${runtimeDir.replace(/\/+$/, '')}/${STATE_DIR}`;
}

/** The recording described by the state file text, or null when it is not a usable state. */
export function parseState(text) {
    let data;
    try {
        data = JSON.parse(text);
    } catch (_e) {
        return null;
    }
    if (data === null || typeof data !== 'object')
        return null;
    const {pid, started, mode} = data;
    if (!Number.isInteger(pid) || pid <= 0 || !Number.isInteger(started) || typeof mode !== 'string')
        return null;
    return {pid, started, mode, paused: data.paused === true};
}

/** `{state, started}` of a process from the text of /proc/<pid>/stat, or null. */
export function parseProcStat(text) {
    if (typeof text !== 'string')
        return null;
    const right = text.lastIndexOf(')');
    if (text.indexOf('(') < 0 || right < 0)
        return null;
    const fields = text.slice(right + 2).trim().split(/\s+/);
    if (fields.length < 20)
        return null;
    const started = Number(fields[19]);
    if (!Number.isInteger(started))
        return null;
    return {state: fields[0], started};
}

/**
 * What the dot shows: the recording must be the very process the state file names (same pid and
 * same start time, so a reused pid does not count) and not a zombie. `proc` is the result of
 * parseProcStat for state.pid.
 */
export function dotFor(state, proc) {
    if (!state || !proc)
        return null;
    if (proc.started !== state.started || proc.state === 'Z' || proc.state === 'X')
        return null;
    return state.paused ? PAUSED : RECORDING;
}
