# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

"""The dot, with a stand-in for GTK and the AppIndicator library (neither is needed to test the
logic; whether the real ones draw the dot is a check on a real desktop)."""

import fcntl
import sys
import threading
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
    dark = indicator.view(rec.State(1, 2, "video", "/f"), lit=False)
    assert (dark.icon, dark.description, dark.pause_label) == (
        APP_ID + "-recording-off",
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
        """The commands of the menu: not the separators."""
        return [i for i in self.all if not i.separator]

    @property
    def key_lines(self):
        """Lines the dot hides until it has something to say: there are none any more."""
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
        self.IndicatorStatus = type("S", (), {"ACTIVE": "active", "PASSIVE": "passive"})
        outer = self

        class FakeIndicator:
            def __init__(self, app_id, icon, category):
                self.args = (app_id, icon, category)
                self.theme = None
                self.status = None
                self.statuses = []
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
                self.statuses.append(status)

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

    def idle_add(self, function, *args):
        function(*args)  # the real one runs it on the GTK thread; here it is the same thing

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
        self.stopped = 0
        self.stop_works = True
        self.stop_fails = None

    def status(self):
        return self.current

    def stop(self):
        self.stopped += 1
        if self.stop_fails is not None:
            raise self.stop_fails
        if self.stop_works:
            self.current = None
        return 0


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
        (APP_ID + "-recording-off", "Recording"),  # the first refresh is the dark half
        (APP_ID + "-paused", "Paused"),
    ]
    assert pause_item.label == "Resume"  # the last label written while paused
    assert toolkit.quit_called and toolkit.timer[0] == 500


def test_a_running_recording_blinks_and_a_paused_one_does_not(tmp_path):
    running = rec.State(1, 2, "video", "/f")
    paused = rec.State(1, 2, "video", "/f", paused=True)
    recorder = StubRecorder(tmp_path, running)
    toolkit = Toolkit([running] * 5 + [paused] * 3 + [None], recorder)
    indicator.run(recorder, toolkit.triple())
    dark, lit = APP_ID + "-recording-off", APP_ID + "-recording"
    assert [icon for icon, _text in toolkit.indicator.icons] == (
        [dark, lit, dark, lit, dark] + [APP_ID + "-paused"] * 3
    )


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


def test_a_resident_dot_stays_while_nothing_records_and_offers_the_commands(tmp_path, monkeypatch):
    spawned = []
    monkeypatch.setattr(indicator, "_spawn", lambda *args: spawned.append(args))
    recorder = StubRecorder(tmp_path, None)
    toolkit = Toolkit([None, None], recorder)
    assert indicator.run(recorder, toolkit.triple(), resident=True) == 0
    dot = toolkit.indicator
    assert dot.args == (APP_ID, APP_ID + "-symbolic", "app-status")
    labels = [item.label for item in dot.menu.items]
    # the order of the menu: the five ways to start, pause, stop, then Settings, About and Quit
    assert labels == [
        "Record screen and sound",
        "Record screen only",
        "Record sound only",
        "Record area and sound",
        "Record area only",
        "Pause",
        "Stop and save",
        "Settings…",
        "About",
        "Quit",
    ]
    assert [item.sensitive for item in dot.menu.items] == [True] * 5 + [False, False] + [True] * 3
    assert not toolkit.quit_called  # nothing recording does not end a resident dot
    assert dot.icons[-1] == (APP_ID + "-symbolic", "Hotrec")
    for item in dot.menu.items[:5]:
        item.handlers["activate"](item)
    assert spawned == [
        ("video-audio",),
        ("video",),
        ("audio",),
        ("region-video-audio",),
        ("region-video",),
    ]


def test_a_resident_dot_follows_a_recording_and_back(tmp_path):
    running = rec.State(1, 2, "video", "/f")
    recorder = StubRecorder(tmp_path, None)
    toolkit = Toolkit([running, rec.State(1, 2, "video", "/f", paused=True), None], recorder)
    indicator.run(recorder, toolkit.triple(), resident=True)
    dot = toolkit.indicator
    assert [icon for icon, _text in dot.icons] == [
        APP_ID + "-symbolic",  # the first look, nothing recording
        APP_ID + "-recording-off",  # the first refresh is the dark half of the blink
        APP_ID + "-paused",
        APP_ID + "-symbolic",
    ]
    assert not toolkit.quit_called


def test_a_resident_dot_while_recording_cannot_start_another(tmp_path):
    recorder = StubRecorder(tmp_path, rec.State(1, 2, "video", "/f"))
    toolkit = Toolkit([], recorder)
    indicator.run(recorder, toolkit.triple(), resident=True)
    sensitive = [i.sensitive for i in toolkit.indicator.menu.items]
    assert sensitive == [False] * 5 + [True] * 5  # pause, stop, the two windows and Quit
    assert toolkit.indicator.args[1] == APP_ID + "-recording"


def wait_for_quit():
    """The stop of Quit runs in a thread of its own: wait for it."""
    for thread in threading.enumerate():
        if thread.name == "hotrec-quit":
            thread.join(10)
            assert not thread.is_alive()


def press_quit(toolkit):
    item = toolkit.indicator.menu.items[-1]
    assert item.label == "Quit"
    item.handlers["activate"](item)
    wait_for_quit()
    return item


def test_quit_is_the_last_row_after_about_and_only_in_the_resident_menu(tmp_path):
    recorder = StubRecorder(tmp_path, None)
    toolkit = Toolkit([], recorder)
    indicator.run(recorder, toolkit.triple(), resident=True)
    assert [i.label for i in toolkit.indicator.menu.items[-2:]] == ["About", "Quit"]
    assert toolkit.indicator.menu.all[-1] is toolkit.indicator.menu.items[-1]

    other = StubRecorder(tmp_path / "other", rec.State(1, 2, "video", "/f"))
    (tmp_path / "other").mkdir()
    plain = Toolkit([], other)
    indicator.run(other, plain.triple())  # the dot of a recording
    assert "Quit" not in [i.label for i in plain.indicator.menu.items]


def test_quit_with_nothing_recording_ends_the_dot(tmp_path):
    recorder = StubRecorder(tmp_path, None)
    toolkit = Toolkit([], recorder)
    indicator.run(recorder, toolkit.triple(), resident=True)
    assert not toolkit.quit_called
    item = press_quit(toolkit)
    assert toolkit.quit_called
    assert toolkit.indicator.statuses == ["active", "passive"]  # the dot is gone from the bar
    assert item.sensitive is False  # no second press while it ends


def test_quit_while_recording_stops_and_saves_first(tmp_path):
    state = rec.State(1, 2, "video", "/f")
    recorder = StubRecorder(tmp_path, state)
    toolkit = Toolkit([], recorder)
    indicator.run(recorder, toolkit.triple(), resident=True)
    order = []
    stop = recorder.stop
    recorder.stop = lambda: (order.append("stop"), stop())[1]
    toolkit.main_quit = lambda: order.append("quit")
    press_quit(toolkit)
    assert order == ["stop", "quit"]
    assert recorder.current is None and recorder.stopped == 1


def test_quit_saves_the_recording_like_stop_and_save_does(world, env, monkeypatch):
    monkeypatch.setattr(indicator, "_spawn", lambda *args: None)
    recorder = world.recorder(env)
    assert recorder.toggle(rec.VIDEO_AUDIO) == 0
    toolkit = Toolkit([], recorder)
    indicator.run(recorder, toolkit.triple(), resident=True)
    assert recorder.status() is not None
    press_quit(toolkit)
    assert recorder.status() is None  # the state is gone: nothing keeps recording
    assert [note[0] for note in world.notes][-1] == "Recording saved"
    assert toolkit.quit_called


def test_quit_leaves_the_dot_when_the_recording_could_not_be_stopped(tmp_path):
    state = rec.State(1, 2, "video", "/f")
    recorder = StubRecorder(tmp_path, state)
    recorder.stop_works = False
    toolkit = Toolkit([], recorder)
    indicator.run(recorder, toolkit.triple(), resident=True)
    item = press_quit(toolkit)
    assert not toolkit.quit_called and item.sensitive is True  # it can be tried again
    assert toolkit.indicator.statuses == ["active"]


def test_quit_survives_a_stop_that_raises(tmp_path):
    recorder = StubRecorder(tmp_path, rec.State(1, 2, "video", "/f"))
    recorder.stop_fails = OSError("gone")
    toolkit = Toolkit([], recorder)
    indicator.run(recorder, toolkit.triple(), resident=True)
    item = press_quit(toolkit)
    assert not toolkit.quit_called and item.sensitive is True


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


ALL_KEYS = {
    "video-audio": "<Primary><Shift>F9",
    "video": "<Control><Shift>f10",
    "audio": "<Primary><Alt>r",
    "pause": "<Super>F12",
    "region-video-audio": "<Primary><Shift>F7",
    "region-video": "<Primary><Shift>F8",
}


def test_each_command_line_carries_its_keys_and_there_is_no_grey_key_list(tmp_path, monkeypatch):
    monkeypatch.setattr(indicator, "_key_source", lambda: KeySource(keys_of(ALL_KEYS)))
    recorder = StubRecorder(tmp_path, None)
    toolkit = Toolkit([], recorder)
    indicator.run(recorder, toolkit.triple(), resident=True)
    menu = toolkit.indicator.menu
    assert [i.label for i in menu.items] == [
        "Record screen and sound (Ctrl+Shift+F9)",
        "Record screen only (Ctrl+Shift+F10)",
        "Record sound only (Ctrl+Alt+R)",
        "Record area and sound (Ctrl+Shift+F7)",
        "Record area only (Ctrl+Shift+F8)",
        "Pause (Super+F12)",
        "Stop and save",
        "Settings…",
        "About",
        "Quit",
    ]
    assert menu.key_lines == []  # the grey duplicate list is gone: the first line is a command
    assert not menu.all[0].separator and "activate" in menu.all[0].handlers
    assert [i.separator for i in menu.all].count(True) == 1  # only before Settings
    assert menu.all[-4].separator


def test_the_pause_line_keeps_its_keys_when_it_turns_into_resume(tmp_path, monkeypatch):
    monkeypatch.setattr(indicator, "_key_source", lambda: KeySource(keys_of(ALL_KEYS)))
    running = rec.State(1, 2, "video", "/f")
    recorder = StubRecorder(tmp_path, running)
    toolkit = Toolkit([rec.State(1, 2, "video", "/f", paused=True)], recorder)
    indicator.run(recorder, toolkit.triple(), resident=True)
    pause_item = toolkit.indicator.menu.items[5]
    assert pause_item.label == "Resume (Super+F12)"


def test_the_dot_of_a_recording_has_pause_with_its_keys_and_stop(tmp_path, monkeypatch):
    monkeypatch.setattr(
        indicator, "_key_source", lambda: KeySource(keys_of({"pause": "<Primary><Shift>F12"}))
    )
    recorder = StubRecorder(tmp_path, rec.State(1, 2, "video", "/f"))
    toolkit = Toolkit([], recorder)
    indicator.run(recorder, toolkit.triple())
    menu = toolkit.indicator.menu
    assert [i.label for i in menu.items] == ["Pause (Ctrl+Shift+F12)", "Stop and save"]
    assert len(menu.all) == 2  # no start lines, no Settings, About or Quit here


def test_a_command_without_keys_is_just_its_name(tmp_path, monkeypatch):
    monkeypatch.setattr(
        indicator, "_key_source", lambda: KeySource(keys_of({"audio": "<Primary><Shift>F11"}))
    )
    recorder = StubRecorder(tmp_path, None)
    toolkit = Toolkit([], recorder)
    indicator.run(recorder, toolkit.triple(), resident=True)
    labels = [i.label for i in toolkit.indicator.menu.items]
    assert labels[:6] == [
        "Record screen and sound",
        "Record screen only",
        "Record sound only (Ctrl+Shift+F11)",
        "Record area and sound",
        "Record area only",
        "Pause",
    ]


def test_without_gnome_settings_the_lines_have_no_keys_and_it_is_not_a_failure(
    tmp_path, monkeypatch
):
    class Gone:
        def bindings(self):
            raise sc.ShortcutError("gsettings not found")

    monkeypatch.setattr(indicator, "_key_source", Gone)
    recorder = StubRecorder(tmp_path, None)
    toolkit = Toolkit([], recorder)
    assert indicator.run(recorder, toolkit.triple(), resident=True) == 0
    assert "(" not in "".join(i.label for i in toolkit.indicator.menu.items)


def test_the_keys_follow_a_change_in_the_gnome_settings(tmp_path, monkeypatch):
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
    assert toolkit.indicator.menu.items[1].label == "Record screen only (Ctrl+Alt+V)"


class FakeWindow:
    closed = False

    def __init__(self):
        self.presented = 0

    def present(self):
        self.presented += 1


def fake_gi(monkeypatch):
    fake_gdk = object()
    monkeypatch.setitem(
        sys.modules,
        "gi",
        types.SimpleNamespace(repository=None, require_version=lambda name, version: None),
    )
    monkeypatch.setitem(sys.modules, "gi.repository", types.SimpleNamespace(Gdk=fake_gdk))
    return fake_gdk


def test_the_settings_item_opens_one_window_and_shows_it_again_while_it_is_open(
    tmp_path, monkeypatch
):
    opened = []

    def open_window(*args):
        opened.append((args, FakeWindow()))
        return opened[-1][1]

    fake_gdk = fake_gi(monkeypatch)
    monkeypatch.setattr(indicator.settings_window, "open_window", open_window)
    recorder = StubRecorder(tmp_path, None)
    toolkit = Toolkit([], recorder)
    indicator.run(recorder, toolkit.triple(), resident=True)
    item = toolkit.indicator.menu.items[-3]
    assert item.label == "Settings…"
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


def test_the_about_item_opens_one_window_and_shows_it_again_while_it_is_open(tmp_path, monkeypatch):
    opened = []

    def open_about(*args):
        opened.append((args, FakeWindow()))
        return opened[-1][1]

    monkeypatch.setattr(indicator.about_window, "open_about", open_about)
    recorder = StubRecorder(tmp_path, None)
    toolkit = Toolkit([], recorder)
    indicator.run(recorder, toolkit.triple(), resident=True)
    item = toolkit.indicator.menu.items[-2]
    assert item.label == "About"
    item.handlers["activate"](item)
    args, window = opened[0]
    assert args == (toolkit.Gtk, APP_ID)
    item.handlers["activate"](item)
    assert len(opened) == 1 and window.presented == 1
    window.closed = True
    item.handlers["activate"](item)
    assert len(opened) == 2


def test_a_saved_key_change_refreshes_the_lines_at_once(tmp_path, monkeypatch):
    """The Settings window calls back after it installed new keys: the menu shows them without
    waiting for the minute."""
    source = KeySource(keys_of({"video": "<Primary><Shift>F10"}))
    monkeypatch.setattr(indicator, "_key_source", lambda: source)
    callbacks = []

    def open_window(Gtk, Gdk, key_source, installer, on_saved, icon):
        callbacks.append(on_saved)
        return FakeWindow()

    fake_gi(monkeypatch)
    monkeypatch.setattr(indicator.settings_window, "open_window", open_window)
    recorder = StubRecorder(tmp_path, None)
    toolkit = Toolkit([], recorder)
    indicator.run(recorder, toolkit.triple(), resident=True)
    menu = toolkit.indicator.menu
    assert menu.items[1].label == "Record screen only (Ctrl+Shift+F10)"
    settings = menu.items[-3]
    settings.handlers["activate"](settings)
    source.bindings_now = keys_of({"video": "<Primary><Alt>v"})
    callbacks[0]()
    assert menu.items[1].label == "Record screen only (Ctrl+Alt+V)"


def test_the_installer_needs_hotrec_on_the_path(monkeypatch):
    monkeypatch.setattr(indicator.shutil, "which", lambda name: None)
    with pytest.raises(sc.ShortcutError):
        indicator._installer()
    monkeypatch.setattr(indicator.shutil, "which", lambda name: "/usr/bin/" + name)
    assert indicator._installer().command == "/usr/bin/hotrec"


def test_key_labels_skip_a_shortcut_without_keys():
    labels = indicator.key_labels(KeySource(keys_of({"audio": "<Primary><Shift>F11"})))
    assert labels == {
        "video-audio": None,
        "video": None,
        "audio": "Ctrl+Shift+F11",
        "pause": None,
        "region-video-audio": None,
        "region-video": None,
    }


def test_with_keys_puts_the_keys_in_brackets_only_when_there_are_some():
    assert indicator.with_keys("Pause", "Ctrl+Shift+F12") == "Pause (Ctrl+Shift+F12)"
    assert indicator.with_keys("Pause", None) == "Pause"
    assert indicator.with_keys("Pause", "") == "Pause"
