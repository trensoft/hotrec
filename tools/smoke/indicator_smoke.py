#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

"""The top bar dot against the real GTK 3 and AppIndicator libraries (no GNOME, no recording).

Run it as a client of a Wayland compositor with a D-Bus session (a headless mutter will do), with
GTK 3, PyGObject and an AppIndicator library installed:

    PYTHONPATH=. python3 tools/smoke/indicator_smoke.py

A stand-in recorder reports "recording", then "paused", then "nothing": the dot must be built
from the real classes, change its icon and its first menu item, and end by itself. Exit status 0
and the line ``indicator smoke: ok`` mean it did. It does not show whether the AppIndicator
extension of GNOME Shell draws the icon: that needs the shell.
"""

import sys
import tempfile
from pathlib import Path

from hotrec import APP_ID, indicator
from hotrec.recorder import State

Gtk, GLib, AppIndicator = indicator._load_toolkit()
print(
    "toolkit: Gtk %d.%d, %s"
    % (Gtk.get_major_version(), Gtk.get_minor_version(), AppIndicator.__name__)
)

created = []
real_new = AppIndicator.Indicator.new


def recording_new(*args):
    dot = real_new(*args)
    created.append(dot)
    return dot


AppIndicator.Indicator.new = recording_new


class StandIn:
    """Reports a state per call, in order; the last one is None."""

    def __init__(self, directory, states):
        self.dir = directory
        self.states = list(states)
        self.seen = []

    def status(self):
        state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
        self.seen.append(state)
        return state


def fail(message):
    print("indicator smoke: FAILED: %s" % message)
    sys.exit(1)


with tempfile.TemporaryDirectory() as tmp:
    running = State(1, 2, "video", "/f/x.mkv")
    paused = State(1, 2, "video", "/f/x.mkv", paused=True)
    # run() asks once for the first view, then the timer asks every 500 ms
    stand_in = StandIn(Path(tmp), [running, running, paused, paused, None])
    labels = []
    icons = []
    original = indicator.view

    def watching(state):
        result = original(state)
        if created and result is not None:
            icons.append(result.icon)
        return result

    indicator.view = watching
    GLib.timeout_add(1200, lambda: (labels.append(items_of(created[0])), False)[1])

    def items_of(dot):
        menu = dot.get_menu()
        return [child.get_label() for child in menu.get_children()]

    code = indicator.run(stand_in, (Gtk, GLib, AppIndicator))

if code != 0:
    fail("run() returned %r" % code)
if len(created) != 1:
    fail("expected one indicator, got %d" % len(created))
dot = created[0]
if dot.get_id() != APP_ID:
    fail("id %r" % dot.get_id())
if dot.get_status() != AppIndicator.IndicatorStatus.ACTIVE:
    fail("status %r" % dot.get_status())
if labels[0][1] != "Stop and save":
    fail("menu %r" % labels)
if indicator.ICON_RECORDING not in icons or indicator.ICON_PAUSED not in icons:
    fail("icons seen %r" % icons)
if stand_in.states != [None]:
    fail("the dot did not read all the states: %r left" % stand_in.states)
print("menu while running: %s" % labels[0])
print("icons shown: %s" % ", ".join(dict.fromkeys(icons)))
print("indicator smoke: ok")
