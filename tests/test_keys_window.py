# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

"""The shortcuts window with a stand-in for GTK 3 (whether the real window looks right and takes the
keys of a real keyboard is a check on a real desktop)."""

from types import SimpleNamespace

import pytest
from test_shortcuts import Gsettings, make

from hotrec import DEVELOPER, __version__, cli, indicator, keys_window
from hotrec import shortcuts as sc

DEFAULTS = {s.slug: s.accelerator for s in sc.SHORTCUTS}


class Widget:
    """Any widget: what it was made with, what was set on it, the handlers connected."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.label = kwargs.get("label", "")
        self.title = kwargs.get("title")
        self.handlers = {}
        self.children = []
        self.destroyed = False
        self.presented = 0

    def __getattr__(self, name):
        if name.startswith(("set_", "add", "get_", "pack_", "attach", "show_")):
            return self._ignore
        raise AttributeError(name)

    def _ignore(self, *args, **kwargs):
        return self

    def connect(self, name, handler, *data):
        self.handlers[name] = (handler, data)

    def set_label(self, text):
        self.label = text

    def set_text(self, text):
        self.label = text

    def present(self):
        self.presented += 1

    def destroy(self):
        self.destroyed = True
        handler = self.handlers.get("destroy")
        if handler:
            handler[0](self)

    def click(self):
        handler, data = self.handlers["clicked"]
        handler(self, *data)


class FakeGtk:
    """Every class the window makes is a ``Widget`` that remembers the order it was made in."""

    Orientation = SimpleNamespace(VERTICAL=1, HORIZONTAL=0)
    Align = SimpleNamespace(END=2)

    def __init__(self):
        self.made = []
        for name in ("Window", "Box", "Label", "Grid", "Button"):
            setattr(self, name, self._maker(name))

    def _maker(self, name):
        def make_widget(**kwargs):
            widget = Widget(**kwargs)
            widget.kind = name
            self.made.append(widget)
            return widget

        return make_widget

    def of(self, kind):
        return [w for w in self.made if w.kind == kind]


class Keys:
    """Stands for ``event_to_keys``: the next key presses, as accelerators (None: a modifier)."""

    def __init__(self, *presses):
        self.presses = list(presses)

    def __call__(self, event):
        return self.presses.pop(0)


def build(g, presses=(), saved=None, grabs=None, command="hotrec"):
    gtk = FakeGtk()
    grabs = [] if grabs is None else grabs
    window = keys_window.KeysWindow(
        gtk,
        lambda: make(g, command),
        lambda: make(g, command),
        Keys(*presses),
        on_saved=lambda: (saved if saved is not None else []).append(True),
        icon_name="id",
        grab=lambda w: grabs.append("grab"),
        release=lambda: grabs.append("release"),
    )
    return window, gtk


def buttons(gtk):
    """The four key buttons, by slug (the last one made is Save)."""
    return dict(zip([s.slug for s in sc.SHORTCUTS], gtk.of("Button")))


def press(window):
    return window.window.handlers["key-press-event"][0](window.window, object())


def test_the_version_line_is_the_version_and_the_maker():
    assert keys_window.version_text() == "%s by %s" % (__version__, DEVELOPER)
    assert keys_window.version_text().endswith(" by TrenSoft")
    assert __version__ == "0.1.2"


def test_the_window_has_the_title_the_version_and_four_rows():
    window, gtk = build(Gsettings())
    assert gtk.of("Window")[0].title == "Keyboard shortcuts"
    labels = [w.label for w in gtk.of("Label")]
    assert keys_window.version_text() in labels
    assert labels[1:5] == [
        "Record screen and sound",
        "Record screen only",
        "Record sound only",
        "Pause or resume recording",
    ]
    assert [b.label for b in gtk.of("Button")] == [
        "Ctrl+Shift+F9",
        "Ctrl+Shift+F10",
        "Ctrl+Shift+F11",
        "Ctrl+Shift+F12",
        "Save",
    ]


def test_first_run_shows_the_default_keys_of_what_the_autostart_set(monkeypatch, env):
    """The 0.1.1 autostart path (hotrec autostart -> setup -> install) puts F9 to F12 into
    GNOME; the window then shows exactly these, and so does the top of the menu."""
    g = Gsettings()
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(
        cli, "Shortcuts", lambda command: sc.Shortcuts(command, run=g, which=lambda n: "/x/" + n)
    )
    monkeypatch.setattr(cli.Recorder, "notify", lambda self, summary, body="": None, raising=False)
    monkeypatch.setattr(indicator, "run", lambda recorder, resident=False: 0)
    assert cli.main(["autostart"]) == 0
    assert {s.slug: g.entries[(sc.path_of(s), "binding")] for s in sc.SHORTCUTS} == DEFAULTS
    window, gtk = build(g)
    assert window.keys == DEFAULTS
    assert [b.label for b in gtk.of("Button")][:4] == [
        "Ctrl+Shift+F9",
        "Ctrl+Shift+F10",
        "Ctrl+Shift+F11",
        "Ctrl+Shift+F12",
    ]
    assert indicator.key_lines(make(g)) == [
        "Ctrl+Shift+F9 - Record screen and sound",
        "Ctrl+Shift+F10 - Record screen only",
        "Ctrl+Shift+F11 - Record sound only",
        "Ctrl+Shift+F12 - Pause or resume recording",
    ]


def test_shortcuts_not_installed_yet_show_the_defaults():
    window, _gtk = build(Gsettings())
    assert window.keys == DEFAULTS


def test_unreadable_settings_show_the_defaults_and_do_not_fail():
    g = Gsettings(fail_on="custom-keybindings")
    window, _gtk = build(g)
    assert window.keys == DEFAULTS


def test_the_window_shows_the_keys_gnome_has_now():
    g = Gsettings()
    make(g).install({"video": "<Primary><Alt>r"})
    window, gtk = build(g)
    assert buttons(gtk)["video"].label == "Ctrl+Alt+R"
    assert buttons(gtk)["audio"].label == "Ctrl+Shift+F11"


def test_a_click_waits_for_the_keys_and_the_next_press_sets_them():
    grabs = []
    window, gtk = build(Gsettings(), ["<Primary><Alt>r"], grabs=grabs)
    button = buttons(gtk)["video"]
    button.click()
    assert button.label == "Press the keys..." and window.waiting == "video"
    assert grabs == ["grab"]
    assert press(window) is True
    assert window.keys["video"] == "<Primary><Alt>r"
    assert button.label == "Ctrl+Alt+R" and window.waiting is None
    assert grabs == ["grab", "release"]


def test_a_modifier_alone_keeps_waiting():
    window, gtk = build(Gsettings(), [None, "<Primary><Shift>F5"])
    buttons(gtk)["pause"].click()
    assert press(window) is True and window.waiting == "pause"
    assert press(window) is True and window.waiting is None
    assert window.keys["pause"] == "<Primary><Shift>F5"


def test_escape_gives_up_and_restores_the_old_keys():
    grabs = []
    window, gtk = build(Gsettings(), ["Escape"], grabs=grabs)
    button = buttons(gtk)["audio"]
    button.click()
    press(window)
    assert window.waiting is None and window.keys["audio"] == DEFAULTS["audio"]
    assert button.label == "Ctrl+Shift+F11" and grabs == ["grab", "release"]


def test_a_bare_letter_is_refused_with_a_message_and_the_wait_goes_on():
    window, gtk = build(Gsettings(), ["a", "<Shift>b", "<Primary>b"])
    buttons(gtk)["video"].click()
    press(window)
    assert window.waiting == "video" and window.message.label == (
        "Use Ctrl, Alt or Super together with the key."
    )
    press(window)  # Shift is no modifier for this
    assert window.waiting == "video"
    press(window)
    assert window.waiting is None and window.keys["video"] == "<Primary>b"
    assert window.message.label == ""


def test_a_function_key_may_stand_alone():
    window, gtk = build(Gsettings(), ["F8"])
    buttons(gtk)["video"].click()
    press(window)
    assert window.keys["video"] == "F8"


def test_a_key_press_when_nothing_is_awaited_is_left_to_gtk():
    window, _gtk = build(Gsettings(), ["<Primary>x"])
    assert press(window) is False
    assert window.keys == DEFAULTS


def test_a_second_click_moves_the_wait_to_the_other_field():
    grabs = []
    window, gtk = build(Gsettings(), grabs=grabs)
    first, second = buttons(gtk)["video"], buttons(gtk)["audio"]
    first.click()
    second.click()
    assert first.label == "Ctrl+Shift+F10" and second.label == "Press the keys..."
    assert window.waiting == "audio"
    assert grabs == ["grab", "release", "grab"]


def test_closing_while_waiting_gives_the_keyboard_back():
    grabs = []
    window, gtk = build(Gsettings(), grabs=grabs)
    buttons(gtk)["video"].click()
    window.window.destroy()
    assert window.closed and grabs == ["grab", "release"]


def test_save_writes_the_keys_with_the_install_logic_and_closes():
    g = Gsettings()
    saved = []
    window, gtk = build(g, ["<Primary><Alt>r"], saved=saved)
    buttons(gtk)["video"].click()
    press(window)
    gtk.of("Button")[-1].click()
    assert g.entries[(sc.path_of(sc.SHORTCUTS[1]), "binding")] == "<Primary><Alt>r"
    assert g.entries[(sc.path_of(sc.SHORTCUTS[0]), "binding")] == "<Primary><Shift>F9"
    assert saved == [True] and window.window.destroyed and window.closed


def test_save_with_nothing_changed_installs_the_defaults():
    g = Gsettings()
    window, gtk = build(g)
    gtk.of("Button")[-1].click()
    assert {s.slug: g.entries[(sc.path_of(s), "binding")] for s in sc.SHORTCUTS} == DEFAULTS


def test_save_refuses_a_key_of_another_program_and_says_so():
    other = sc.PATH_PREFIX + "custom0/"
    g = Gsettings("['%s']" % other, {(other, "binding"): "<Super>t"})
    saved = []
    window, gtk = build(g, ["<Super>t"], saved=saved)
    buttons(gtk)["video"].click()
    press(window)
    gtk.of("Button")[-1].click()
    assert window.message.label.startswith("Could not set the keyboard shortcuts: ")
    assert other in window.message.label and "Super+T" in window.message.label
    assert not window.closed and saved == []
    assert (other, "binding") in g.entries and g.entries[(other, "binding")] == "<Super>t"
    assert not any(c[1] == "set" for c in g.calls)  # nothing was written


def test_a_foreign_key_spelled_differently_is_still_a_conflict():
    other = sc.PATH_PREFIX + "custom0/"
    g = Gsettings("['%s']" % other, {(other, "binding"): "<Control><Shift>f9"})
    with pytest.raises(sc.ShortcutConflict):
        make(g).install()
    g2 = Gsettings("['%s']" % other, {(other, "binding"): "<Ctrl><Alt>R"})
    with pytest.raises(sc.ShortcutConflict):
        make(g2).install({"video": "<Primary><Alt>r"})


def test_save_refuses_the_same_keys_twice_before_touching_gnome():
    g = Gsettings()
    window, gtk = build(g, ["<Primary><Shift>F9"])
    buttons(gtk)["video"].click()
    press(window)
    assert window.duplicates() == ["video-audio", "video"]
    gtk.of("Button")[-1].click()
    assert window.message.label == "Two of the shortcuts have the same keys."
    assert g.calls[-1][1] == "get" and not window.closed
    assert not any(c[1] in ("set", "reset") for c in g.calls)


def test_save_when_hotrec_cannot_be_found_is_a_message(monkeypatch):
    def broken():
        raise sc.ShortcutError("hotrec is not on the PATH")

    gtk = FakeGtk()
    window = keys_window.KeysWindow(gtk, lambda: make(Gsettings()), broken, Keys())
    gtk.of("Button")[-1].click()
    assert window.message.label == (
        "Could not set the keyboard shortcuts: hotrec is not on the PATH"
    )
    assert not window.closed


def test_a_gsettings_failure_while_saving_is_a_message():
    window, gtk = build(Gsettings(fail_on="set"))
    gtk.of("Button")[-1].click()
    assert window.message.label.startswith("Could not set the keyboard shortcuts: ")
    assert not window.closed


# --- reading a key press of GTK 3 ------------------------------------------------------------


class FakeGdk:
    SHIFT, CONTROL, MOD1, SUPER = 1, 4, 8, 64
    KEY_ISO_Left_Tab, KEY_Tab = 0xFE20, 0xFF09
    ModifierType = SimpleNamespace(SHIFT_MASK=1, CONTROL_MASK=4, MOD1_MASK=8, SUPER_MASK=64)
    NAMES = {0xFFC6: "F9", 0x72: "r", 0x52: "R", 0xFF09: "Tab", 0xFFE3: "Control_L", 0x21: "exclam"}

    def __init__(self, translate):
        self.translate = translate
        outer = self
        self.Keymap = SimpleNamespace(
            get_for_display=lambda display: SimpleNamespace(
                translate_keyboard_state=lambda code, state, group: outer.translate(
                    code, state, group
                )
            )
        )
        self.Display = SimpleNamespace(get_default=lambda: object())

    @staticmethod
    def keyval_to_lower(value):
        return 0x72 if value == 0x52 else value

    def keyval_name(self, value):
        return self.NAMES.get(value)


GTK_MASK = SimpleNamespace(accelerator_get_default_mod_mask=lambda: 1 | 4 | 8 | 64)


def accelerator(keyval, state, consumed=0, found=True):
    gdk = FakeGdk(lambda code, st, group: (found, keyval, group, 0, consumed))
    event = SimpleNamespace(hardware_keycode=1, state=state, group=0)
    return keys_window.event_to_accelerator(gdk, GTK_MASK, event)


def test_event_ctrl_shift_f9():
    assert accelerator(0xFFC6, 1 | 4) == "<Primary><Shift>F9"


def test_event_ctrl_alt_letter():
    assert accelerator(0x72, 4 | 8) == "<Primary><Alt>r"


def test_event_a_shift_the_layout_used_for_the_capital_is_kept_as_shift():
    assert accelerator(0x52, 1 | 4, consumed=1) == "<Primary><Shift>r"


def test_event_super_and_the_shift_that_made_the_symbol_does_not_count():
    assert accelerator(0x21, 1 | 64, consumed=1) == "<Super>exclam"


def test_event_a_modifier_alone_is_nothing_yet():
    assert accelerator(0xFFE3, 4) is None


def test_event_unknown_key_is_nothing():
    assert accelerator(0x72, 4, found=False) is None


def test_event_shift_tab_is_tab_with_shift():
    assert accelerator(FakeGdk.KEY_ISO_Left_Tab, 1) == "<Shift>Tab"


def test_event_bare_escape():
    gdk = FakeGdk(lambda c, s, g: (True, 0xFF1B, g, 0, 0))
    gdk.NAMES = {0xFF1B: "Escape"}
    event = SimpleNamespace(hardware_keycode=1, state=0, group=0)
    assert keys_window.event_to_accelerator(gdk, GTK_MASK, event) == "Escape"
