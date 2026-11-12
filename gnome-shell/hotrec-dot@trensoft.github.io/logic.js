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

/**
 * The major version of the Shell from its PACKAGE_VERSION ("49.8", "50.rc", "50.alpha.1"), or null
 * when the text is not one.
 */
export function shellMajor(version) {
    const match = typeof version === 'string' ? /^(\d+)(\.|$)/.exec(version) : null;
    return match ? Number(match[1]) : null;
}

/**
 * The parameters of addTopChrome for the dot. It must be above a fullscreen window (trackFullscreen
 * off) and must not reserve screen space (affectsStruts off). Up to GNOME 49 it also says that the
 * dot is not part of the input region (affectsInputRegion off: the region only counts on X11, and
 * the dot takes no input); GNOME 50 dropped the X11 session and the parameter with it, and its
 * LayoutManager throws "Unrecognized parameter" on it. A version that is not known gets the
 * parameters of the newest Shell, as the dot cannot be shown at all with the one that throws.
 */
export function chromeParams(shellVersion) {
    const params = {affectsStruts: false, trackFullscreen: false};
    const major = shellMajor(shellVersion);
    if (major !== null && major < 50)
        params.affectsInputRegion = false;
    return params;
}
