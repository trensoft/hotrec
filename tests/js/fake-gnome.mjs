// SPDX-FileCopyrightText: 2026 TrenSoft
// SPDX-License-Identifier: GPL-3.0-or-later

// Stands in for the GNOME Shell modules that extension.js imports (gi://St, gi://Gio, gi://GLib,
// gi://Meta and the resource:// modules of the Shell), so the extension can run under plain node.
// Load it with `node --import ./fake-gnome.mjs`. Every fake delegates to `globalThis.world`, which each test
// replaces with a fresh one (see world.mjs).
import {registerHooks} from 'node:module';

const PREFIX = 'fake-gnome:';
// config.js is a constant of the real Shell. Which version it has is chosen by the importer: the
// test imports a copy of extension.js with `?shell=<version>` and that copy gets that version.
const CONFIG = 'resource:///org/gnome/shell/misc/config.js';
const MODULES = {
    'gi://St': {default: 'St'},
    'gi://Gio': {default: 'Gio'},
    'gi://GLib': {default: 'GLib'},
    'gi://Meta': {default: 'Meta'},
    'resource:///org/gnome/shell/extensions/extension.js': {names: ['Extension']},
    'resource:///org/gnome/shell/ui/main.js': {names: ['layoutManager']},
};

registerHooks({
    resolve(specifier, context, nextResolve) {
        if (specifier === CONFIG) {
            const version = new URL(context.parentURL).searchParams.get('shell') ?? '49.8';
            return {url: `${PREFIX}${CONFIG}?shell=${encodeURIComponent(version)}`, shortCircuit: true};
        }
        if (specifier in MODULES)
            return {url: PREFIX + specifier, shortCircuit: true};
        if (specifier.startsWith('gi://') || specifier.startsWith('resource://'))
            throw new Error(`extension.js imports ${specifier}, which the fake GNOME does not have`);
        return nextResolve(specifier, context);
    },
    load(url, context, nextLoad) {
        if (!url.startsWith(PREFIX))
            return nextLoad(url, context);
        if (url.startsWith(PREFIX + CONFIG)) {
            const version = new URL(url.slice(PREFIX.length)).searchParams.get('shell');
            return {format: 'module', source: `export const PACKAGE_VERSION = ${JSON.stringify(version)};`, shortCircuit: true};
        }
        const spec = MODULES[url.slice(PREFIX.length)];
        const key = JSON.stringify(url.slice(PREFIX.length));
        const source = spec.default
            ? `export default globalThis.fakeModules[${key}];`
            : spec.names.map(n => `export const ${n} = globalThis.fakeModules[${key}].${n};`).join('\n');
        return {format: 'module', source, shortCircuit: true};
    },
});
