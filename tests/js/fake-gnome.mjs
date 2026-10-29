// SPDX-FileCopyrightText: 2026 TrenSoft
// SPDX-License-Identifier: GPL-3.0-or-later

// Stands in for the GNOME Shell modules that extension.js imports (gi://St, gi://Gio, gi://GLib and
// the resource:// modules of the Shell), so the extension can run under plain node. Load it with
// `node --import ./fake-gnome.mjs`. Every fake delegates to `globalThis.world`, which each test
// replaces with a fresh one (see world.mjs).
import {registerHooks} from 'node:module';

const PREFIX = 'fake-gnome:';
const MODULES = {
    'gi://St': {default: 'St'},
    'gi://Gio': {default: 'Gio'},
    'gi://GLib': {default: 'GLib'},
    'resource:///org/gnome/shell/extensions/extension.js': {names: ['Extension']},
    'resource:///org/gnome/shell/ui/main.js': {names: ['layoutManager']},
};

registerHooks({
    resolve(specifier, context, nextResolve) {
        if (specifier in MODULES)
            return {url: PREFIX + specifier, shortCircuit: true};
        if (specifier.startsWith('gi://') || specifier.startsWith('resource://'))
            throw new Error(`extension.js imports ${specifier}, which the fake GNOME does not have`);
        return nextResolve(specifier, context);
    },
    load(url, context, nextLoad) {
        if (!url.startsWith(PREFIX))
            return nextLoad(url, context);
        const spec = MODULES[url.slice(PREFIX.length)];
        const key = JSON.stringify(url.slice(PREFIX.length));
        const source = spec.default
            ? `export default globalThis.fakeModules[${key}];`
            : spec.names.map(n => `export const ${n} = globalThis.fakeModules[${key}].${n};`).join('\n');
        return {format: 'module', source, shortCircuit: true};
    },
});
