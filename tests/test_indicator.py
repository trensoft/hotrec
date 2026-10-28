# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

"""The dot, with a stand-in for GTK and the AppIndicator library (neither is needed to test the
logic; whether the real ones draw the dot is a check on a real desktop)."""

import fcntl
import sys

from hotrec import APP_ID, indicator
from hotrec import recorder as rec


def test_view_for_each_state():
    assert indicator.view(None) is None
    running = indicator.view(rec.State(1, 2, "video", "/f"))
    assert (running.icon, running.description, running.pause_label) == (
        APP_ID + "-recording",
        "Recording",
        "Pause",
    )
    paused = indicator.view(rec.State(1, 2, "video", "/f", paused=True))
    assert (paused.icon, paused.description, paused.pause_label) == (
        APP_ID + "-paused",
        "Paused",
        "Resume",
    )


def test_the_icon_theme_is_the_checkouts_data_icons():
    path = indicator.icon_theme_dir()
    assert path is not None and path.endswith("data/icons")


class Item:
    def __init__(self, label=""):
        self.label = label
        self.handlers = {}

    def connect(self, name, handler):
        self.handlers[name] = handler

    def set_label(self, text):
        self.label = text


class Menu:
    def __init__(self):
        self.items = []
        self.shown = False

    def append(self, item):
        self.items.append(item)

    def show_all(self):
        self.shown = True


class Toolkit:
    """Gtk, GLib and AppIndicator in one object, and a main loop that runs the timer a few times."""

    def __init__(self, states, recorder):
        self.states = states
        self.recorder = recorder
        self.quit_called = False
        self.timer = None
        self.indicator = None
        self.Menu = Menu
        self.IndicatorCategory = type("C", (), {"APPLICATION_STATUS": "app-status"})
        self.IndicatorStatus = type("S", (), {"ACTIVE": "active"})
        outer = self

        class FakeIndicator:
            def __init__(self, app_id, icon, category):
                self.args = (app_id, icon, category)
                self.theme = None
                self.status = None
                self.menu = None
                self.icons = []
                outer.indicator = self

            @classmethod
            def new(cls, app_id, icon, category):
                return cls(app_id, icon, category)

            def set_icon_theme_path(self, path):
                self.theme = path

            def set_status(self, status):
                self.status = status

            def set_menu(self, menu):
                self.menu = menu

            def set_icon_full(self, icon, description):
                self.icons.append((icon, description))

        self.Indicator = FakeIndicator
        self.Gtk = self
        self.GLib = self
        self.AppIndicator = self

    def MenuItem(self, label=""):
        return Item(label)

    def timeout_add(self, milliseconds, function):
        self.timer = (milliseconds, function)

    def main(self):
        while self.states:
            self.recorder.current = self.states.pop(0)
            if not self.timer[1]():
                break

    def main_quit(self):
        self.quit_called = True

    def triple(self):
        return (self.Gtk, self.GLib, self.AppIndicator)


class StubRecorder:
    def __init__(self, directory, current):
        self.dir = directory
        self.current = current

    def status(self):
        return self.current


def test_the_dot_is_built_updated_and_quits_with_the_recording(tmp_path):
    state = rec.State(1, 2, "video", "/f")
    recorder = StubRecorder(tmp_path, state)
    toolkit = Toolkit([state, rec.State(1, 2, "video", "/f", paused=True), None], recorder)
    assert indicator.run(recorder, toolkit.triple()) == 0
    dot = toolkit.indicator
    assert dot.args == (APP_ID, APP_ID + "-recording", "app-status")
    assert dot.status == "active" and dot.menu.shown
    assert dot.theme and dot.theme.endswith("data/icons")
    pause_item, stop_item = dot.menu.items
    assert stop_item.label == "Stop and save"
    assert dot.icons == [
        (APP_ID + "-recording", "Recording"),
        (APP_ID + "-paused", "Paused"),
    ]
    assert pause_item.label == "Resume"  # the last label written while paused
    assert toolkit.quit_called and toolkit.timer[0] == 500


def test_the_menu_runs_the_commands(tmp_path, monkeypatch):
    spawned = []
    monkeypatch.setattr(indicator, "_spawn", lambda *args: spawned.append(args))
    state = rec.State(1, 2, "audio", "/f")
    recorder = StubRecorder(tmp_path, state)
    toolkit = Toolkit([], recorder)
    indicator.run(recorder, toolkit.triple())
    pause_item, stop_item = toolkit.indicator.menu.items
    pause_item.handlers["activate"](pause_item)
    stop_item.handlers["activate"](stop_item)
    assert spawned == [("pause",), ("stop",)]


def test_spawn_runs_this_python_with_the_hotrec_module(monkeypatch):
    calls = []
    monkeypatch.setattr(indicator.subprocess, "Popen", lambda cmd, **kw: calls.append((cmd, kw)))
    indicator._spawn("pause")
    assert calls[0][0] == [sys.executable, "-m", "hotrec", "pause"]
    assert calls[0][1]["start_new_session"] is True


def test_nothing_recording_means_no_dot(tmp_path):
    recorder = StubRecorder(tmp_path, None)
    toolkit = Toolkit([], recorder)
    assert indicator.run(recorder, toolkit.triple()) == 0
    assert toolkit.indicator is None


def test_a_second_dot_exits_at_once(tmp_path):
    recorder = StubRecorder(tmp_path, rec.State(1, 2, "video", "/f"))
    holder = open(tmp_path / "indicator.lock", "a")
    fcntl.flock(holder, fcntl.LOCK_EX)
    try:
        toolkit = Toolkit([], recorder)
        assert indicator.run(recorder, toolkit.triple()) == 0
        assert toolkit.indicator is None
    finally:
        holder.close()


def test_missing_gtk_is_a_message_not_a_traceback(tmp_path, monkeypatch, capsys):
    recorder = StubRecorder(tmp_path, rec.State(1, 2, "video", "/f"))

    def broken():
        raise ValueError("Namespace Gtk not available for version 3.0")

    monkeypatch.setattr(indicator, "_load_toolkit", broken)
    assert indicator.run(recorder) == 1
    assert "GTK 3" in capsys.readouterr().err
