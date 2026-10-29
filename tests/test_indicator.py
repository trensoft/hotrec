# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

"""The dot, with a stand-in for GTK and the AppIndicator library (neither is needed to test the
logic; whether the real ones draw the dot is a check on a real desktop)."""

import fcntl
import sys
import types

import pytest

from hotrec import APP_ID, indicator
from hotrec import recorder as rec
from hotrec import shortcuts as sc


@pytest.fixture(autouse=True)
def no_real_gsettings(monkeypatch):
    """The dot reads the keys from GNOME; a test never asks the machine it runs on."""
    monkeypatch.setattr(indicator, "_key_source", lambda: KeySource({}))


class KeySource:
    def __init__(self, bindings):
        self.bindings_now = bindings

    def bindings(self):
        return dict(self.bindings_now)


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
        self.sensitive = True
        self.no_show_all = False
        self.visible = True
        self.separator = False

    def set_no_show_all(self, value):
        self.no_show_all = value
        self.visible = not value  # show_all leaves it hidden until it is shown

    def show(self):
        self.visible = True

    def hide(self):
        self.visible = False

    def set_sensitive(self, value):
        self.sensitive = value

    def connect(self, name, handler):
        self.handlers[name] = handler

    def set_label(self, text):
        self.label = text


class Menu:
    def __init__(self):
        self.all = []
        self.shown = False

    @property
    def items(self):
        """The commands of the menu: not the grey key lines at the top, not the separators."""
        return [i for i in self.all if not i.no_show_all and not i.separator]

    @property
    def key_lines(self):
        return [i for i in self.all if i.no_show_all]

    def append(self, item):
        self.all.append(item)

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

    def SeparatorMenuItem(self):
        item = Item()
        item.separator = True
        return item

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


def test_a_resident_dot_stays_while_nothing_records_and_offers_the_three_modes(
    tmp_path, monkeypatch
):
    spawned = []
    monkeypatch.setattr(indicator, "_spawn", lambda *args: spawned.append(args))
    recorder = StubRecorder(tmp_path, None)
    toolkit = Toolkit([None, None], recorder)
    assert indicator.run(recorder, toolkit.triple(), resident=True) == 0
    dot = toolkit.indicator
    assert dot.args == (APP_ID, APP_ID + "-symbolic", "app-status")
    labels = [item.label for item in dot.menu.items]
    assert labels == [
        "Record screen and sound",
        "Record screen only",
        "Record sound only",
        "Pause",
        "Stop and save",
        "Set keyboard shortcuts...",
    ]
    assert [item.sensitive for item in dot.menu.items] == [True, True, True, False, False, True]
    assert not toolkit.quit_called  # nothing recording does not end a resident dot
    assert dot.icons[-1] == (APP_ID + "-symbolic", "Hotrec")
    for item in dot.menu.items[:3]:
        item.handlers["activate"](item)
    assert spawned == [("video-audio",), ("video",), ("audio",)]


def test_a_resident_dot_follows_a_recording_and_back(tmp_path):
    running = rec.State(1, 2, "video", "/f")
    recorder = StubRecorder(tmp_path, None)
    toolkit = Toolkit([running, rec.State(1, 2, "video", "/f", paused=True), None], recorder)
    indicator.run(recorder, toolkit.triple(), resident=True)
    dot = toolkit.indicator
    assert [icon for icon, _text in dot.icons] == [
        APP_ID + "-symbolic",  # the first look, nothing recording
        APP_ID + "-recording",
        APP_ID + "-paused",
        APP_ID + "-symbolic",
    ]
    assert not toolkit.quit_called


def test_a_resident_dot_while_recording_cannot_start_another(tmp_path):
    recorder = StubRecorder(tmp_path, rec.State(1, 2, "video", "/f"))
    toolkit = Toolkit([], recorder)
    indicator.run(recorder, toolkit.triple(), resident=True)
    sensitive = [i.sensitive for i in toolkit.indicator.menu.items]
    assert sensitive == [False, False, False, True, True, True]  # the last: the keys window
    assert toolkit.indicator.args[1] == APP_ID + "-recording"


def test_a_second_resident_dot_exits_at_once(tmp_path):
    recorder = StubRecorder(tmp_path, None)
    holder = open(tmp_path / "indicator.lock", "a")
    fcntl.flock(holder, fcntl.LOCK_EX)
    try:
        toolkit = Toolkit([], recorder)
        assert indicator.run(recorder, toolkit.triple(), resident=True) == 0
        assert toolkit.indicator is None
    finally:
        holder.close()


def keys_of(g_bindings):
    return {s.slug: g_bindings.get(s.slug) for s in sc.SHORTCUTS}


def test_the_top_of_the_menu_lists_the_keys_grey_and_not_clickable(tmp_path, monkeypatch):
    monkeypatch.setattr(
        indicator,
        "_key_source",
        lambda: KeySource(
            keys_of(
                {
                    "video-audio": "<Primary><Shift>F9",
                    "video": "<Control><Shift>f10",
                    "audio": "<Primary><Alt>r",
                    "pause": "<Super>F12",
                }
            )
        ),
    )
    recorder = StubRecorder(tmp_path, None)
    toolkit = Toolkit([], recorder)
    indicator.run(recorder, toolkit.triple(), resident=True)
    menu = toolkit.indicator.menu
    assert menu.all[:4] == menu.key_lines  # at the top
    assert [i.label for i in menu.key_lines] == [
        "Ctrl+Shift+F9 - Record screen and sound",
        "Ctrl+Shift+F10 - Record screen only",
        "Ctrl+Alt+R - Record sound only",
        "Super+F12 - Pause or resume recording",
    ]
    assert all(not i.sensitive and i.visible for i in menu.key_lines)
    assert all("activate" not in i.handlers for i in menu.key_lines)
    assert menu.all[4].separator


def test_the_key_lines_are_there_in_the_dot_of_a_recording_too(tmp_path, monkeypatch):
    monkeypatch.setattr(
        indicator, "_key_source", lambda: KeySource(keys_of({"pause": "<Primary><Shift>F12"}))
    )
    recorder = StubRecorder(tmp_path, rec.State(1, 2, "video", "/f"))
    toolkit = Toolkit([], recorder)
    indicator.run(recorder, toolkit.triple())
    menu = toolkit.indicator.menu
    assert [i.label for i in menu.items] == ["Pause", "Stop and save"]  # no keys window here
    assert [(i.label, i.visible) for i in menu.key_lines] == [
        ("", False),
        ("", False),
        ("", False),
        ("Ctrl+Shift+F12 - Pause or resume recording", True),
    ]


def test_without_gnome_settings_the_key_lines_are_hidden_not_a_failure(tmp_path, monkeypatch):
    class Gone:
        def bindings(self):
            raise sc.ShortcutError("gsettings not found")

    monkeypatch.setattr(indicator, "_key_source", Gone)
    recorder = StubRecorder(tmp_path, None)
    toolkit = Toolkit([], recorder)
    assert indicator.run(recorder, toolkit.triple(), resident=True) == 0
    assert not any(i.visible for i in toolkit.indicator.menu.key_lines)


def test_the_key_lines_follow_a_change_in_the_gnome_settings(tmp_path, monkeypatch):
    source = KeySource(keys_of({"video": "<Primary><Shift>F10"}))
    monkeypatch.setattr(indicator, "_key_source", lambda: source)
    recorder = StubRecorder(tmp_path, None)
    states = [None] * indicator.KEYS_REREAD_TICKS
    toolkit = Toolkit(states, recorder)
    original = toolkit.main

    def main():
        source.bindings_now = keys_of({"video": "<Primary><Alt>v"})
        original()

    toolkit.main = main
    indicator.run(recorder, toolkit.triple(), resident=True)
    assert toolkit.indicator.menu.key_lines[1].label == "Ctrl+Alt+V - Record screen only"


def test_the_keys_item_opens_one_window_and_shows_it_again_while_it_is_open(tmp_path, monkeypatch):
    class Window:
        closed = False
        presented = 0

        def present(self):
            self.presented += 1

    opened = []

    def open_window(*args):
        opened.append((args, Window()))
        return opened[-1][1]

    fake_gdk = object()
    monkeypatch.setitem(
        sys.modules,
        "gi",
        types.SimpleNamespace(repository=None, require_version=lambda name, version: None),
    )
    monkeypatch.setitem(sys.modules, "gi.repository", types.SimpleNamespace(Gdk=fake_gdk))
    monkeypatch.setattr(indicator.keys_window, "open_window", open_window)
    recorder = StubRecorder(tmp_path, None)
    toolkit = Toolkit([], recorder)
    indicator.run(recorder, toolkit.triple(), resident=True)
    item = toolkit.indicator.menu.items[-1]
    assert item.label == "Set keyboard shortcuts..."
    item.handlers["activate"](item)
    args, window = opened[0]
    assert args[0] is toolkit.Gtk and args[1] is fake_gdk
    assert args[2] is indicator._key_source and args[3] is indicator._installer
    assert args[5] == APP_ID
    item.handlers["activate"](item)
    assert len(opened) == 1 and window.presented == 1  # the open window comes forward
    window.closed = True
    item.handlers["activate"](item)
    assert len(opened) == 2  # a closed one is replaced


def test_the_installer_needs_hotrec_on_the_path(monkeypatch):
    monkeypatch.setattr(indicator.shutil, "which", lambda name: None)
    with pytest.raises(sc.ShortcutError):
        indicator._installer()
    monkeypatch.setattr(indicator.shutil, "which", lambda name: "/usr/bin/" + name)
    assert indicator._installer().command == "/usr/bin/hotrec"


def test_key_lines_skip_a_shortcut_without_keys():
    lines = indicator.key_lines(KeySource(keys_of({"audio": "<Primary><Shift>F11"})))
    assert lines == [None, None, "Ctrl+Shift+F11 - Record sound only", None]
