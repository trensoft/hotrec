# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Settings window with a stand-in for GTK 3 (whether the real window looks right, fits on a
screen and takes the keys of a real keyboard is a check on a real desktop). The settings file and
the shortcuts are real, in a temporary home and against a fake ``gsettings``."""

from types import SimpleNamespace

from test_shortcuts import Gsettings, make

from hotrec import DEVELOPER, __version__, cli, config, indicator, settings_window
from hotrec import shortcuts as sc

DEFAULTS = {s.slug: s.accelerator for s in sc.SHORTCUTS}


class Widget:
    """Any widget: what it was made with, what was set on it, the handlers connected. The ones
    that hold a value act like GTK's: a change by ``set_*`` emits the signal, a change to the
    value it already has does not."""

    def __init__(self, kind="", **kwargs):
        self.kind = kind
        self.kwargs = kwargs
        self.label = kwargs.get("label", "")
        self.title = kwargs.get("title")
        self.handlers = {}
        self.destroyed = False
        self.presented = 0
        self.sensitive = True
        self.visible = True
        self.no_show_all = False
        self.active = False
        self.value = 0.0
        self.active_id = None
        self.options = []
        self.group = [self]
        self.tooltip = None
        self.children = []

    def __getattr__(self, name):
        if name.startswith(("set_", "add", "get_", "pack_", "attach", "show_")):
            return self._ignore
        raise AttributeError(name)

    def _ignore(self, *args, **kwargs):
        return self

    def connect(self, name, handler, *data):
        self.handlers[name] = (handler, data)

    def emit(self, name):
        handler = self.handlers.get(name)
        if handler:
            handler[0](self, *handler[1])

    def set_label(self, text):
        self.label = text

    def set_text(self, text):
        self.label = text

    def set_tooltip_text(self, text):
        self.tooltip = text

    def set_sensitive(self, value):
        self.sensitive = value

    def set_visible(self, value):
        self.visible = value

    def set_no_show_all(self, value):
        self.no_show_all = value
        if value:
            self.visible = False  # show_all leaves it hidden until it is shown

    def get_active(self):
        return self.active

    def set_active(self, value):
        if value == self.active:
            return
        if value:  # a radio button group has one on: the others go off first
            for other in self.group:
                if other is not self and other.active:
                    other.active = False
                    other.emit("toggled")
        self.active = value
        self.emit("toggled")

    def get_value(self):
        return self.value

    def set_value(self, value):
        if value != self.value:
            self.value = value
            self.emit("value-changed")

    def append(self, ident, text):
        self.options.append((ident, text))

    def get_active_id(self):
        return self.active_id

    def set_active_id(self, ident):
        if ident != self.active_id:
            self.active_id = ident
            self.emit("changed")

    def present(self):
        self.presented += 1

    def destroy(self):
        self.destroyed = True
        self.emit("destroy")

    def click(self):
        self.emit("clicked")


class FakeGtk:
    """Every class the window makes is a ``Widget`` that remembers the order it was made in."""

    Orientation = SimpleNamespace(VERTICAL=1, HORIZONTAL=0)
    Align = SimpleNamespace(END=2)

    def __init__(self):
        self.made = []
        for name in ("Window", "Box", "Label", "Grid", "Button", "ComboBoxText", "Scale"):
            setattr(self, name, self._maker(name))
        self.Adjustment = lambda **kwargs: SimpleNamespace(**kwargs)
        gtk = self
        self.RadioButton = SimpleNamespace(new_with_label_from_widget=gtk._radio)

    def _maker(self, name):
        def make_widget(**kwargs):
            widget = Widget(name, **kwargs)
            self.made.append(widget)
            return widget

        return make_widget

    def _radio(self, member, label):
        button = Widget("RadioButton", label=label)
        if member is not None:
            button.group = member.group
            member.group.append(button)
        self.made.append(button)
        return button

    def of(self, kind):
        return [w for w in self.made if w.kind == kind]


class Keys:
    """Stands for ``event_to_keys``: the next key presses, as accelerators (None: a modifier)."""

    def __init__(self, *presses):
        self.presses = list(presses)

    def __call__(self, event):
        return self.presses.pop(0)


class Choices:
    """Stands for the folder chooser and the yes/no question: what they were asked and what they
    answer (a folder, or None for cancelled; yes or no)."""

    def __init__(self, folders=(), yes=True):
        self.folders = list(folders)
        self.yes = yes
        self.asked = []
        self.questions = []

    def choose(self, window, title, current):
        self.asked.append((title, current))
        return self.folders.pop(0)

    def confirm(self, window, question):
        self.questions.append(question)
        return self.yes


def build(
    g,
    env,
    presses=(),
    saved=None,
    grabs=None,
    command="hotrec",
    choices=None,
    codecs=frozenset({"h264", "h265"}),
    installer=None,
):
    gtk = FakeGtk()
    grabs = [] if grabs is None else grabs
    choices = choices or Choices()
    window = settings_window.SettingsWindow(
        gtk,
        lambda: make(g, command),
        installer or (lambda: make(g, command)),
        Keys(*presses),
        on_saved=lambda: (saved if saved is not None else []).append(True),
        icon_name="id",
        grab=lambda w: grabs.append("grab"),
        release=lambda: grabs.append("release"),
        load_config=lambda: config.load(env)[0],
        write_config=lambda updates: config.set_values(updates, env),
        choose_folder=choices.choose,
        confirm=choices.confirm,
        video_codecs=lambda: codecs,
    )
    return window, gtk


def key_buttons(gtk):
    """The six key buttons, by slug (they are the first Buttons made)."""
    return dict(zip([s.slug for s in sc.SHORTCUTS], gtk.of("Button")))


def press(window):
    return window.window.handlers["key-press-event"][0](window.window, object())


def conf_text(env):
    path = config.config_path(env)
    return path.read_text() if path.exists() else ""


def set_slider(window, key, step):
    window.sliders[key].set_value(step)


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
    return settings_window.event_to_accelerator(gdk, GTK_MASK, event)


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
    assert settings_window.event_to_accelerator(gdk, GTK_MASK, event) == "Escape"


# -- the window and its shortcuts -------------------------------------------------------------


def test_the_version_line_is_the_version_and_the_maker():
    assert settings_window.version_text() == "%s by %s" % (__version__, DEVELOPER)
    assert settings_window.version_text().endswith(" by TrenSoft")
    assert __version__ == "0.1.6"


def test_the_window_is_called_settings_and_has_the_four_sections_in_order(env):
    window, gtk = build(Gsettings(), env)
    assert gtk.of("Window")[0].title == "Settings"
    labels = [w.label for w in gtk.of("Label")]
    headings = [x for x in labels if x in ("Keyboard shortcuts", "Video", "Sound", "Folders")]
    assert headings == ["Keyboard shortcuts", "Video", "Sound", "Folders"]
    assert settings_window.version_text() in labels


def test_the_window_has_every_control_of_the_spec(env):
    window, gtk = build(Gsettings(), env)
    labels = [w.label for w in gtk.of("Label")]
    for text in (
        "Video codec",
        "Video bitrate",
        "Frame rate",
        "Video file format",
        "Sound codec for sound-only recordings",
        "Sound bitrate with video",
        "Sound bitrate for sound-only recordings",
        "Videos are saved in",
        "Sound recordings are saved in",
    ):
        assert text in labels
    assert [b.label for b in gtk.of("RadioButton")] == [
        "H.264 (plays everywhere)",
        "H.265 (about half the file size)",
        "MKV",
        "MP4",
    ]
    assert gtk.of("ComboBoxText")[0].options == [("mp3", "MP3"), ("aac", "AAC"), ("opus", "Opus")]
    assert len(gtk.of("Scale")) == 4
    assert [b.label for b in gtk.of("Button")][6:] == [
        "Choose…",
        "Choose…",
        "Reset to defaults",
        "Close",
    ]
    # what the spec took out is not there: no normalize, no mono/stereo, no preset, no expert mode
    everything = " ".join(str(w.label) for w in gtk.made).lower()
    for gone in ("normal", "mono", "stereo", "preset", "advanced", "expert"):
        assert gone not in everything
    assert "Save" not in [b.label for b in gtk.of("Button")]  # every control writes at once


def test_the_six_key_rows_are_in_the_order_of_the_shortcuts(env):
    window, gtk = build(Gsettings(), env)
    labels = [w.label for w in gtk.of("Label")]
    start = labels.index("Click a field, then press the new keys. Escape cancels.") + 1
    assert labels[start : start + 6] == [
        "Record screen and sound",
        "Record screen only",
        "Record sound only",
        "Pause or resume recording",
        "Record area and sound",
        "Record area only",
    ]
    assert [b.label for b in gtk.of("Button")][:6] == [
        "Ctrl+Shift+F9",
        "Ctrl+Shift+F10",
        "Ctrl+Shift+F11",
        "Ctrl+Shift+F12",
        "Ctrl+Shift+F7",
        "Ctrl+Shift+F8",
    ]


def test_first_run_shows_the_default_keys_of_what_the_autostart_set(monkeypatch, env):
    """The 0.1.1 autostart path (hotrec autostart -> setup -> install) puts F9 to F12 into
    GNOME (and the two area keys F7 and F8); the window then shows exactly these, and so does the
    menu."""
    g = Gsettings()
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(
        cli, "Shortcuts", lambda command: sc.Shortcuts(command, run=g, which=lambda n: "/x/" + n)
    )
    monkeypatch.setattr(cli.Recorder, "notify", lambda self, summary, body="": None, raising=False)
    monkeypatch.setattr(indicator, "run", lambda recorder, resident=False: 0)
    assert cli.main(["autostart"]) == 0
    assert {s.slug: g.entries[(sc.path_of(s), "binding")] for s in sc.SHORTCUTS} == DEFAULTS
    window, gtk = build(g, env)
    assert window.keys == DEFAULTS
    assert indicator.key_labels(make(g)) == {
        "video-audio": "Ctrl+Shift+F9",
        "video": "Ctrl+Shift+F10",
        "audio": "Ctrl+Shift+F11",
        "pause": "Ctrl+Shift+F12",
        "region-video-audio": "Ctrl+Shift+F7",
        "region-video": "Ctrl+Shift+F8",
    }


def test_shortcuts_not_installed_yet_show_the_defaults(env):
    window, _gtk = build(Gsettings(), env)
    assert window.keys == DEFAULTS


def test_unreadable_settings_show_the_defaults_and_do_not_fail(env):
    window, _gtk = build(Gsettings(fail_on="custom-keybindings"), env)
    assert window.keys == DEFAULTS


def test_the_window_shows_the_keys_gnome_has_now(env):
    g = Gsettings()
    make(g).install({"video": "<Primary><Alt>r"})
    window, gtk = build(g, env)
    assert key_buttons(gtk)["video"].label == "Ctrl+Alt+R"
    assert key_buttons(gtk)["audio"].label == "Ctrl+Shift+F11"


def test_a_click_waits_for_the_keys_and_the_next_press_sets_them_at_once(env):
    g = Gsettings()
    grabs, saved = [], []
    window, gtk = build(g, env, ["<Primary><Alt>r"], saved=saved, grabs=grabs)
    button = key_buttons(gtk)["video"]
    button.click()
    assert button.label == "Press the keys..." and window.waiting == "video"
    assert grabs == ["grab"]
    assert press(window) is True
    assert window.keys["video"] == "<Primary><Alt>r"
    assert button.label == "Ctrl+Alt+R" and window.waiting is None
    assert grabs == ["grab", "release"]
    assert make(g).bindings()["video"] == "<Primary><Alt>r"  # in GNOME now, no Save button
    assert saved == [True]  # the menu is told


def test_a_changed_key_leaves_the_other_five_as_they_were(env):
    g = Gsettings()
    window, gtk = build(g, env, ["<Primary><Alt>r"])
    key_buttons(gtk)["video"].click()
    press(window)
    assert make(g).bindings() == {**DEFAULTS, "video": "<Primary><Alt>r"}


def test_a_modifier_alone_keeps_waiting(env):
    window, gtk = build(Gsettings(), env, [None, "<Primary><Shift>F5"])
    key_buttons(gtk)["pause"].click()
    assert press(window) is True and window.waiting == "pause"
    assert press(window) is True and window.waiting is None
    assert window.keys["pause"] == "<Primary><Shift>F5"


def test_escape_gives_up_and_restores_the_old_keys_without_touching_gnome(env):
    g = Gsettings()
    grabs = []
    window, gtk = build(g, env, ["Escape"], grabs=grabs)
    button = key_buttons(gtk)["audio"]
    button.click()
    calls = len(g.calls)
    assert press(window) is True
    assert button.label == "Ctrl+Shift+F11" and window.waiting is None
    assert grabs == ["grab", "release"]
    assert len(g.calls) == calls


def test_a_bare_letter_is_refused_with_a_message_and_the_wait_goes_on(env):
    g = Gsettings()
    window, gtk = build(g, env, ["a", "<Primary>a"])
    key_buttons(gtk)["audio"].click()
    assert press(window) is True
    assert window.waiting == "audio"
    assert window.message.label == "Use Ctrl, Alt or Super together with the key."
    assert press(window) is True
    assert window.waiting is None and window.keys["audio"] == "<Primary>a"
    assert window.message.label == ""


def test_a_function_key_may_stand_alone(env):
    window, gtk = build(Gsettings(), env, ["F5"])
    key_buttons(gtk)["audio"].click()
    press(window)
    assert window.keys["audio"] == "F5" and window.waiting is None


def test_a_key_press_when_nothing_is_awaited_is_left_to_gtk(env):
    window, _gtk = build(Gsettings(), env, [])
    assert press(window) is False


def test_a_second_click_moves_the_wait_to_the_other_field(env):
    grabs = []
    window, gtk = build(Gsettings(), env, [], grabs=grabs)
    buttons = key_buttons(gtk)
    buttons["video"].click()
    buttons["audio"].click()
    assert window.waiting == "audio"
    assert buttons["video"].label == "Ctrl+Shift+F10"  # the first one shows its keys again
    assert grabs == ["grab", "release", "grab"]


def test_closing_while_waiting_gives_the_keyboard_back(env):
    grabs = []
    window, gtk = build(Gsettings(), env, [], grabs=grabs)
    key_buttons(gtk)["video"].click()
    window.window.destroy()
    assert window.closed is True and grabs == ["grab", "release"]


def test_a_key_of_another_program_is_refused_and_the_row_goes_back(env):
    g = Gsettings(
        listing=ast_list(sc.PATH_PREFIX + "custom0/"),
        entries={
            (sc.PATH_PREFIX + "custom0/", "binding"): "<Primary><Alt>r",
            (sc.PATH_PREFIX + "custom0/", "command"): "other",
            (sc.PATH_PREFIX + "custom0/", "name"): "Other",
        },
    )
    saved = []
    window, gtk = build(g, env, ["<Primary><Alt>r"], saved=saved)
    button = key_buttons(gtk)["video"]
    button.click()
    press(window)
    assert window.message.label.startswith("Could not set the keyboard shortcuts: ")
    assert button.label == "Ctrl+Shift+F10" and window.keys["video"] == "<Primary><Shift>F10"
    assert saved == []
    assert not window.closed  # the window stays: choose other keys


def ast_list(*paths):
    return "[%s]" % ", ".join("'%s'" % p for p in paths)


def test_a_foreign_key_spelled_differently_is_still_a_conflict(env):
    g = Gsettings(
        listing=ast_list(sc.PATH_PREFIX + "custom0/"),
        entries={(sc.PATH_PREFIX + "custom0/", "binding"): "<Control><Alt>r"},
    )
    window, gtk = build(g, env, ["<Primary><Alt>r"])
    key_buttons(gtk)["video"].click()
    press(window)
    assert window.message.label.startswith("Could not set the keyboard shortcuts")


def test_the_same_keys_twice_are_refused_before_gnome_is_touched(env):
    g = Gsettings()
    window, gtk = build(g, env, ["<Primary><Shift>F11"])  # the keys of "audio"
    key_buttons(gtk)["video"].click()
    calls = len(g.calls)
    press(window)
    assert window.message.label == "Two of the shortcuts have the same keys."
    assert key_buttons(gtk)["video"].label == "Ctrl+Shift+F10"
    assert window.keys["video"] == "<Primary><Shift>F10"
    assert len(g.calls) == calls


def test_when_hotrec_cannot_be_found_the_change_is_a_message(env):
    def broken():
        raise sc.ShortcutError("hotrec is not on the PATH")

    window, gtk = build(Gsettings(), env, ["<Primary><Alt>r"], installer=broken)
    key_buttons(gtk)["video"].click()
    press(window)
    assert window.message.label == (
        "Could not set the keyboard shortcuts: hotrec is not on the PATH"
    )
    assert key_buttons(gtk)["video"].label == "Ctrl+Shift+F10"


def test_a_gsettings_failure_while_setting_is_a_message(env):
    g = Gsettings(fail_on="set")
    window, gtk = build(g, env, ["<Primary><Alt>r"])
    key_buttons(gtk)["video"].click()
    press(window)
    assert window.message.label.startswith("Could not set the keyboard shortcuts")
    assert window.keys["video"] == "<Primary><Shift>F10"


def test_duplicates_names_every_row_that_shares_keys():
    keys = {"a": "<Primary><Shift>F9", "b": "<Control><Shift>f9", "c": "F5"}
    assert settings_window.SettingsWindow.duplicates(keys) == ["a", "b"]
    assert settings_window.SettingsWindow.duplicates({"a": "F5", "b": "F6"}) == []


# -- video ------------------------------------------------------------------------------------


def test_the_defaults_of_today_are_what_the_window_starts_with_and_nothing_is_written(env):
    before = conf_text(env)
    window, gtk = build(Gsettings(), env)
    first = conf_text(env)  # reading the settings makes the file when there is none, once
    assert window.codec_buttons["h264"].active and not window.codec_buttons["h265"].active
    assert window.container_buttons["mkv"].active
    assert window.audio_codec_box.active_id == "mp3"
    steps = settings_window
    assert window.sliders["VIDEO_KBPS"].value == steps.VIDEO_BITRATE_STEPS.index(12000)
    assert window.sliders["FPS"].value == steps.FPS_STEPS.index(30)
    assert window.sliders["AAC_KBPS"].value == steps.SOUND_BITRATE_STEPS.index(160)
    assert window.sliders["MP3_KBPS"].value == steps.SOUND_BITRATE_STEPS.index(192)
    assert window.slider_texts["VIDEO_KBPS"].label == "12.0 Mbit/s"
    assert window.slider_texts["FPS"].label == "30 fps"
    assert window.slider_texts["AAC_KBPS"].label == "160 kbit/s"
    assert window.slider_texts["MP3_KBPS"].label == "192 kbit/s"
    assert first.count("\n") > 5 and "VIDEO_KBPS=12000" in first and before == ""
    assert conf_text(env) == first  # showing the values is not changing them


def test_every_default_of_the_settings_file_is_a_step_of_its_slider():
    cfg = config.default_config()
    for steps, value in (
        (settings_window.VIDEO_BITRATE_STEPS, cfg.video_kbps),
        (settings_window.FPS_STEPS, cfg.fps),
        (settings_window.SOUND_BITRATE_STEPS, cfg.aac_kbps),
        (settings_window.SOUND_BITRATE_STEPS, cfg.mp3_kbps),
    ):
        assert value in steps


def test_the_sliders_run_over_the_ranges_of_the_spec():
    assert settings_window.SOUND_BITRATE_STEPS[0] == 32
    assert settings_window.SOUND_BITRATE_STEPS[-1] == 320
    steps = settings_window.VIDEO_BITRATE_STEPS
    assert list(steps) == sorted(set(steps))
    ratios = [b / a for a, b in zip(steps, steps[1:])]
    assert 1.1 < min(ratios) and max(ratios) < 1.4  # exponential: every step about a quarter more
    assert steps[-1] / steps[0] == 200


def test_the_video_codec_is_a_choice_and_h265_is_written_as_h265(env):
    window, _gtk = build(Gsettings(), env)
    window.codec_buttons["h265"].set_active(True)
    assert 'VIDEO_CODEC="h265"' in conf_text(env)
    assert config.load(env)[0].video_codec == "h265"
    window.codec_buttons["h264"].set_active(True)
    assert config.load(env)[0].video_codec == "h264"
    assert not window.codec_buttons["h265"].active


def test_h265_cannot_be_chosen_when_the_card_cannot_encode_it(env):
    window, _gtk = build(Gsettings(), env, codecs=frozenset({"h264"}))
    assert window.codec_buttons["h265"].sensitive is False
    assert window.codec_buttons["h264"].sensitive is True
    assert window.h265_missing_note.visible is True
    assert window.h265_missing_note.label == (
        "H.265 is not available: the graphics card cannot encode it."
    )
    assert window.h265_play_note.visible is False


def test_h265_cannot_be_chosen_when_nothing_can_be_asked(env):
    window, _gtk = build(Gsettings(), env, codecs=frozenset())
    assert window.codec_buttons["h265"].sensitive is False
    assert window.h265_missing_note.visible is True


def test_h265_can_be_chosen_when_the_card_can_and_the_note_about_playing_follows_the_choice(env):
    window, _gtk = build(Gsettings(), env)
    assert window.codec_buttons["h265"].sensitive is True
    assert window.h265_missing_note.visible is False
    assert window.h265_play_note.visible is False  # H.264 plays everywhere
    window.codec_buttons["h265"].set_active(True)
    assert window.h265_play_note.visible is True
    assert window.h265_play_note.label == (
        "H.265 videos may need an extra codec to play on Windows and in some browsers."
    )
    window.codec_buttons["h264"].set_active(True)
    assert window.h265_play_note.visible is False


def test_h265_already_in_the_file_is_shown_even_if_the_card_cannot(env):
    config.set_values({"VIDEO_CODEC": "h265"}, env)
    window, _gtk = build(Gsettings(), env, codecs=frozenset({"h264"}))
    assert window.codec_buttons["h265"].active  # the file is not changed behind the user's back
    assert window.h265_missing_note.visible is True
    assert window.h265_play_note.visible is False  # one note, the one that matters
    assert "VIDEO_CODEC" in conf_text(env)


def test_the_video_bitrate_slider_writes_the_step_it_is_on(env):
    window, _gtk = build(Gsettings(), env)
    steps = settings_window.VIDEO_BITRATE_STEPS
    set_slider(window, "VIDEO_KBPS", steps.index(800))
    assert config.load(env)[0].video_kbps == 800
    assert window.slider_texts["VIDEO_KBPS"].label == "800 kbit/s"
    set_slider(window, "VIDEO_KBPS", steps.index(25000))
    assert config.load(env)[0].video_kbps == 25000
    assert window.slider_texts["VIDEO_KBPS"].label == "25.0 Mbit/s"
    set_slider(window, "VIDEO_KBPS", steps.index(1000))
    assert window.slider_texts["VIDEO_KBPS"].label == "1.0 Mbit/s"


def test_a_bitrate_between_two_steps_is_shown_as_it_is_and_kept_until_the_slider_moves(env):
    config.set_values({"VIDEO_KBPS": "15500"}, env)
    window, _gtk = build(Gsettings(), env)
    steps = settings_window.VIDEO_BITRATE_STEPS
    assert window.sliders["VIDEO_KBPS"].value == steps.index(15000)  # the nearest
    assert window.slider_texts["VIDEO_KBPS"].label == "15.5 Mbit/s"  # but the real number
    assert config.load(env)[0].video_kbps == 15500
    set_slider(window, "VIDEO_KBPS", steps.index(20000))
    assert config.load(env)[0].video_kbps == 20000


def test_nearest_step_goes_by_ratio_not_by_difference():
    steps = settings_window.VIDEO_BITRATE_STEPS
    assert steps[settings_window.nearest_step(steps, 700)] == 700
    assert steps[settings_window.nearest_step(steps, 1)] == 500
    assert steps[settings_window.nearest_step(steps, 10**7)] == 100000
    # 10970 is nearer to 10000 by difference (970 against 1030) but nearer to 12000 by ratio
    assert steps[settings_window.nearest_step(steps, 10970)] == 12000
    assert steps[settings_window.nearest_step(steps, 10900)] == 10000


def test_the_rate_text_is_kbits_below_a_thousand_and_mbits_from_there():
    assert settings_window.rate_text(32) == "32 kbit/s"
    assert settings_window.rate_text(999) == "999 kbit/s"
    assert settings_window.rate_text(1000) == "1.0 Mbit/s"
    assert settings_window.rate_text(12000) == "12.0 Mbit/s"
    assert settings_window.rate_text(100000) == "100.0 Mbit/s"


def test_the_frame_rate_slider_writes_fps(env):
    window, _gtk = build(Gsettings(), env)
    set_slider(window, "FPS", settings_window.FPS_STEPS.index(60))
    assert config.load(env)[0].fps == 60
    assert window.slider_texts["FPS"].label == "60 fps"


def test_the_file_format_is_a_choice_between_mkv_and_mp4(env):
    window, _gtk = build(Gsettings(), env)
    window.container_buttons["mp4"].set_active(True)
    assert config.load(env)[0].container == "mp4"
    assert not window.container_buttons["mkv"].active
    window.container_buttons["mkv"].set_active(True)
    assert config.load(env)[0].container == "mkv"


def test_a_toggle_that_is_a_radio_button_going_off_writes_nothing(env):
    window, _gtk = build(Gsettings(), env)
    window.codec_buttons["h265"].set_active(True)
    before = conf_text(env)
    window.codec_buttons["h264"].emit("toggled")  # inactive now: the "off" half of a switch
    assert conf_text(env) == before and config.load(env)[0].video_codec == "h265"


def test_a_value_that_is_the_same_does_not_write_twice(env):
    window, _gtk = build(Gsettings(), env)
    window.codec_buttons["h265"].set_active(True)
    mtime = config.config_path(env).stat().st_mtime_ns
    window.codec_buttons["h265"].set_active(True)  # already on: GTK does not even signal
    assert config.config_path(env).stat().st_mtime_ns == mtime


# -- sound ------------------------------------------------------------------------------------


def test_the_sound_codec_of_a_sound_only_recording_is_a_choice(env):
    window, _gtk = build(Gsettings(), env)
    window.audio_codec_box.set_active_id("opus")
    assert config.load(env)[0].audio_codec == "opus"
    window.audio_codec_box.set_active_id("aac")
    assert config.load(env)[0].audio_codec == "aac"
    window.audio_codec_box.set_active_id("mp3")
    assert config.load(env)[0].audio_codec == "mp3"


def test_the_note_about_the_sound_codec_shows_unless_the_codec_is_aac(env):
    window, _gtk = build(Gsettings(), env)
    note = window.sound_note
    assert (
        note.label == "Applies only to sound-only recordings. With video, the sound is always AAC."
    )
    assert note.visible is True  # MP3 is the default: the note is there from the start
    window.audio_codec_box.set_active_id("aac")
    assert note.visible is False
    window.audio_codec_box.set_active_id("opus")
    assert note.visible is True
    window.audio_codec_box.set_active_id("mp3")
    assert note.visible is True


def test_the_note_is_hidden_from_the_start_when_the_file_says_aac(env):
    config.set_values({"AUDIO_CODEC": "aac"}, env)
    window, _gtk = build(Gsettings(), env)
    assert window.sound_note.visible is False


def test_there_is_no_sound_codec_choice_for_video_the_sound_inside_is_aac(env):
    window, gtk = build(Gsettings(), env)
    assert len(gtk.of("ComboBoxText")) == 1  # one chooser, and it is the sound-only one
    assert "Sound bitrate with video" in [w.label for w in gtk.of("Label")]


def test_the_two_sound_bitrate_sliders_write_their_own_keys(env):
    window, _gtk = build(Gsettings(), env)
    steps = settings_window.SOUND_BITRATE_STEPS
    set_slider(window, "AAC_KBPS", steps.index(320))
    set_slider(window, "MP3_KBPS", steps.index(32))
    cfg = config.load(env)[0]
    assert (cfg.aac_kbps, cfg.mp3_kbps) == (320, 32)
    assert window.slider_texts["AAC_KBPS"].label == "320 kbit/s"
    assert window.slider_texts["MP3_KBPS"].label == "32 kbit/s"


# -- a write that fails ----------------------------------------------------------------------


def test_a_setting_that_cannot_be_saved_is_said_and_the_control_goes_back(env, monkeypatch):
    window, _gtk = build(Gsettings(), env)

    def broken(updates, env=None):
        raise OSError(13, "Permission denied", "/home/test/.config/hotrec.conf")

    monkeypatch.setattr(config, "set_values", broken)
    window._write_config = broken
    set_slider(window, "FPS", settings_window.FPS_STEPS.index(60))
    assert "Permission denied" in window.message.label
    assert "hotrec.conf" in window.message.label
    assert window.sliders["FPS"].value == settings_window.FPS_STEPS.index(30)  # the file's value
    assert window.slider_texts["FPS"].label == "30 fps"
    window.codec_buttons["h265"].set_active(True)
    assert window.codec_buttons["h264"].active and not window.codec_buttons["h265"].active


def test_the_message_of_a_failure_goes_when_the_next_write_works(env):
    window, _gtk = build(Gsettings(), env)
    window._say("old problem")
    set_slider(window, "FPS", settings_window.FPS_STEPS.index(60))
    assert window.message.label == ""


# -- folders ----------------------------------------------------------------------------------


def home_folder(env):
    return env["HOME"] + "/Videos/Hotrec"


def test_the_folder_rows_name_the_kinds_and_show_the_default_folder(env):
    window, gtk = build(Gsettings(), env)
    assert window.folder_labels["video"].label == home_folder(env)
    assert window.folder_labels["audio"].label == home_folder(env)
    assert window.folder_labels["video"].tooltip == home_folder(env)


def test_a_folder_that_is_set_is_shown(env):
    config.set_values({"AUDIO_FOLDER": "/mnt/music"}, env)
    window, _gtk = build(Gsettings(), env)
    assert window.folder_labels["audio"].label == "/mnt/music"
    assert window.folder_labels["video"].label == home_folder(env)


def test_choosing_a_folder_shows_it_and_writes_only_that_key(env):
    choices = Choices(["/mnt/clips"])
    window, gtk = build(Gsettings(), env, choices=choices)
    window.folder_buttons["video"].click()
    assert window.folder_labels["video"].label == "/mnt/clips"
    assert window.folder_labels["audio"].label == home_folder(env)
    text = conf_text(env)
    assert 'VIDEO_FOLDER="/mnt/clips"' in text and "AUDIO_FOLDER=" not in text.replace(
        "# AUDIO_FOLDER=", ""
    )
    assert config.load(env)[0].video_folder == "/mnt/clips"


def test_a_cancelled_chooser_changes_nothing(env):
    window, _gtk = build(Gsettings(), env, choices=Choices([None]))
    before = conf_text(env)
    window.folder_buttons["audio"].click()
    assert window.folder_labels["audio"].label == home_folder(env)
    assert conf_text(env) == before


def test_the_chooser_starts_at_the_folder_the_kind_has_now(env):
    config.set_values({"AUDIO_FOLDER": "/mnt/music"}, env)
    choices = Choices([None, None])
    window, _gtk = build(Gsettings(), env, choices=choices)
    window.folder_buttons["audio"].click()
    window.folder_buttons["video"].click()
    assert choices.asked == [
        ("Choose a folder", "/mnt/music"),
        ("Choose a folder", home_folder(env)),
    ]


def test_choosing_the_default_folder_again_unsets_the_kind(env):
    config.set_values({"VIDEO_FOLDER": "/mnt/clips"}, env)
    window, _gtk = build(Gsettings(), env, choices=Choices([home_folder(env)]))
    window.folder_buttons["video"].click()
    assert config.load(env)[0].video_folder == ""
    assert "\nVIDEO_FOLDER=" not in conf_text(env)
    assert window.folder_labels["video"].label == home_folder(env)


def test_a_folder_under_home_is_written_with_home_in_front(env):
    window, _gtk = build(Gsettings(), env, choices=Choices([env["HOME"] + "/Clips"]))
    window.folder_buttons["video"].click()
    assert 'VIDEO_FOLDER="$HOME/Clips"' in conf_text(env)
    assert window.folder_labels["video"].label == env["HOME"] + "/Clips"


def test_a_folder_click_gives_up_a_key_that_is_awaited(env):
    grabs = []
    window, gtk = build(Gsettings(), env, choices=Choices([None]), grabs=grabs)
    key_buttons(gtk)["video"].click()
    window.folder_buttons["audio"].click()
    assert window.waiting is None and grabs == ["grab", "release"]
    assert key_buttons(gtk)["video"].label == "Ctrl+Shift+F10"


# -- reset and close --------------------------------------------------------------------------


def changed_everything(window, env):
    steps = settings_window
    window.codec_buttons["h265"].set_active(True)
    window.container_buttons["mp4"].set_active(True)
    window.audio_codec_box.set_active_id("opus")
    set_slider(window, "VIDEO_KBPS", steps.VIDEO_BITRATE_STEPS.index(3000))
    set_slider(window, "FPS", steps.FPS_STEPS.index(60))
    set_slider(window, "AAC_KBPS", steps.SOUND_BITRATE_STEPS.index(64))
    set_slider(window, "MP3_KBPS", steps.SOUND_BITRATE_STEPS.index(96))


def test_reset_asks_first_and_a_no_changes_nothing(env):
    g = Gsettings()
    choices = Choices(yes=False)
    window, _gtk = build(g, env, choices=choices)
    changed_everything(window, env)
    before = conf_text(env)
    calls = len(g.calls)
    window.reset_button.click()
    assert choices.questions == ["Reset every setting to its default value?"]
    assert conf_text(env) == before and len(g.calls) == calls
    assert config.load(env)[0].video_codec == "h265"


def test_reset_with_a_yes_gives_every_setting_its_default_back(env):
    window, _gtk = build(Gsettings(), env, choices=Choices([None, None], yes=True))
    config.set_values({"FOLDER": "/data/rec", "VIDEO_FOLDER": "/mnt/clips"}, env)
    changed_everything(window, env)
    window.reset_button.click()
    cfg = config.load(env)[0]
    assert cfg == config.default_config(env)
    assert (cfg.video_codec, cfg.video_kbps, cfg.fps, cfg.aac_kbps, cfg.mp3_kbps) == (
        "h264",
        12000,
        30,
        160,
        192,
    )
    assert (cfg.container, cfg.audio_codec) == ("mkv", "mp3")


def test_reset_puts_the_controls_back_too_without_writing_again(env):
    window, _gtk = build(Gsettings(), env, choices=Choices(yes=True))
    changed_everything(window, env)
    window.reset_button.click()
    assert window.codec_buttons["h264"].active and window.container_buttons["mkv"].active
    assert window.audio_codec_box.active_id == "mp3"
    assert window.slider_texts["VIDEO_KBPS"].label == "12.0 Mbit/s"
    assert window.slider_texts["FPS"].label == "30 fps"
    assert window.slider_texts["AAC_KBPS"].label == "160 kbit/s"
    assert window.slider_texts["MP3_KBPS"].label == "192 kbit/s"
    assert window.h265_play_note.visible is False and window.sound_note.visible is True
    assert window.folder_labels["video"].label == home_folder(env)
    text = conf_text(env)
    assert all(line.lstrip().startswith("#") or not line.strip() for line in text.splitlines()), (
        text
    )  # no setting is left in the file


def test_reset_puts_the_six_default_keys_back_and_tells_the_menu(env):
    g = Gsettings()
    saved = []
    window, gtk = build(g, env, ["<Primary><Alt>r"], saved=saved, choices=Choices(yes=True))
    key_buttons(gtk)["video"].click()
    press(window)
    assert make(g).bindings()["video"] == "<Primary><Alt>r"
    saved.clear()
    window.reset_button.click()
    assert make(g).bindings() == DEFAULTS
    assert window.keys == DEFAULTS and key_buttons(gtk)["video"].label == "Ctrl+Shift+F10"
    assert saved == [True]


def test_reset_leaves_the_settings_reset_even_when_the_keys_cannot_be_set(env):
    def broken():
        raise sc.ShortcutError("hotrec is not on the PATH")

    window, _gtk = build(Gsettings(), env, installer=broken, choices=Choices(yes=True))
    config.set_values({"FPS": "60"}, env)
    window.reset_button.click()
    assert config.load(env)[0].fps == 30
    assert "hotrec is not on the PATH" in window.message.label


def test_reset_stops_when_the_file_cannot_be_written(env):
    g = Gsettings()
    window, _gtk = build(g, env, choices=Choices(yes=True))
    config.set_values({"FPS": "60"}, env)

    def broken(updates):
        raise OSError(30, "Read-only file system")

    window._write_config = broken
    calls = len(g.calls)
    window.reset_button.click()
    assert "Read-only" in window.message.label
    assert len(g.calls) == calls  # the keys were not touched
    assert config.load(env)[0].fps == 60


def test_reset_gives_up_a_key_that_is_awaited(env):
    grabs = []
    window, gtk = build(Gsettings(), env, grabs=grabs, choices=Choices(yes=True))
    key_buttons(gtk)["audio"].click()
    window.reset_button.click()
    assert window.waiting is None and grabs == ["grab", "release"]


def test_close_closes_the_window_and_nothing_is_lost(env):
    window, _gtk = build(Gsettings(), env)
    set_slider(window, "FPS", settings_window.FPS_STEPS.index(60))
    window.close_button.click()
    assert window.window.destroyed and window.closed
    assert config.load(env)[0].fps == 60


def test_present_brings_the_window_forward(env):
    window, _gtk = build(Gsettings(), env)
    window.present()
    assert window.window.presented == 1


def test_the_settings_apply_from_the_next_recording_through_the_real_config_loader(env):
    """The recorder reads the file at every start, so what the window wrote is what the next
    recording uses."""
    from hotrec import recorder as rec

    window, _gtk = build(Gsettings(), env)
    window.codec_buttons["h265"].set_active(True)
    window.audio_codec_box.set_active_id("opus")
    set_slider(window, "VIDEO_KBPS", settings_window.VIDEO_BITRATE_STEPS.index(5000))
    cfg = config.load(env)[0]
    command = rec.video_command(cfg, True, rec.Path("/f.mkv"))
    assert command[command.index("-k") + 1] == "hevc"
    assert command[command.index("-q") + 1] == "5000"
    assert command[command.index("-ac") + 1] == "aac"  # the sound of a video is AAC whatever else
    audio = rec.audio_command(cfg, "x.monitor", rec.Path("/f.opus"))
    assert audio[audio.index("-c:a") + 1] == "libopus"
