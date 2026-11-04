# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Settings window (menu of the top bar dot): every setting of Hotrec in one place.

Keyboard shortcuts: one row each, its name and a button with the keys it has. A click on the
button waits for the new keys ("Press the keys..."), Escape gives that up. A new combination is
written into the GNOME custom keybindings at once with ``Shortcuts.install``, the same code
``hotrec setup`` uses: a key that another program's custom keybinding already has is refused (and
said so), nothing of other programs is overwritten.

Video: the codec (H.264, or H.265 when the graphics card can encode it, see ``codecs``), the bit
rate (a slider on an exponential scale: the steps are 14-33 % apart, so a few clicks
cover 500 kbit/s and 100 Mbit/s), the frame rate and the file format. Sound: the codec of a
sound-only recording and two bit rates, one for the sound inside a video (always AAC) and one for
a sound-only recording. Folders: where videos and where sound recordings are saved.

Every control writes its value into ``~/.config/hotrec.conf`` (``config.set_values``) the moment it
changes, so there is no Save button; "Reset to defaults" asks, then removes every setting from the
file and puts the six default keys back; "Close" closes. At the bottom right the version and the
maker ("0.1.6 by TrenSoft"), as in the settings window of Slideshow Lock.

The window shows the keys the entries have now; shortcuts that are not installed yet show the
default keys (Ctrl+Shift+F7 to F12), which is what the next change of a key would set.

GTK 3 is passed in (``indicator`` loads it when the dot starts); the Gdk part of reading a key
press is a separate function, so the logic runs under test without a display.
"""

from __future__ import annotations

import logging
import math
import os
from typing import Any, Callable, Dict, FrozenSet, List, Mapping, Optional, Sequence

from hotrec import DEVELOPER, _, __version__, codecs, config
from hotrec.shortcuts import (
    SHORTCUTS,
    ShortcutError,
    Shortcuts,
    accelerator_label,
    accelerator_problem,
    canonical_accelerator,
    same_accelerator,
    shortcut_names,
)

_LOG = logging.getLogger(__name__)

# Keys that are no key combination by themselves: pressing Ctrl first must not end the wait.
_MODIFIER_KEYS = frozenset(
    {
        "Shift_L",
        "Shift_R",
        "Control_L",
        "Control_R",
        "Alt_L",
        "Alt_R",
        "Super_L",
        "Super_R",
        "Meta_L",
        "Meta_R",
        "Hyper_L",
        "Hyper_R",
        "ISO_Level3_Shift",
        "ISO_Level5_Shift",
        "Caps_Lock",
        "Num_Lock",
        "Scroll_Lock",
    }
)

EventToKeys = Callable[[Any], Optional[str]]
ChooseFolder = Callable[[Any, str, str], Optional[str]]  # (window, title, current) -> folder

Confirm = Callable[[Any, str], bool]  # (window, question) -> yes

# The two folder rows: kind, the settings key it is saved under.
FOLDER_KEYS = (("video", "VIDEO_FOLDER"), ("audio", "AUDIO_FOLDER"))

# The positions of the sliders. The video bit rate is an exponential scale: each step is the
# previous one times 1.14 to 1.33, and 12000 (the default) is one of them. The others are the
# values a person asks for. A value in the settings file that is not a step is shown by the nearest
# step and stays as it is until the slider is moved.
VIDEO_BITRATE_STEPS = (
    500, 600, 700, 800, 1000, 1200, 1500, 2000, 2500, 3000, 4000, 5000, 6000,
    8000, 10000, 12000, 15000, 20000, 25000, 30000, 40000, 50000, 60000, 80000, 100000,
)  # fmt: skip
FPS_STEPS = (10, 15, 24, 25, 30, 48, 50, 60, 90, 120, 144)
SOUND_BITRATE_STEPS = (32, 48, 64, 96, 128, 160, 192, 224, 256, 320)  # kbit/s, fixed steps

# The choices: the value in the settings file, and the name a person reads (not translated: they
# are the names of formats).
CONTAINER_NAMES = (("mkv", "MKV"), ("mp4", "MP4"))
AUDIO_CODEC_NAMES = (("mp3", "MP3"), ("aac", "AAC"), ("opus", "Opus"))


def nearest_step(steps: Sequence[int], value: int) -> int:
    """The index of the step closest to ``value``, by ratio (the scale is exponential)."""
    return min(range(len(steps)), key=lambda i: abs(math.log(value / steps[i])))


def rate_text(kbps: int) -> str:
    """ "800 kbit/s", and from 1000 on "12.0 Mbit/s"."""
    if kbps < 1000:
        return _("%d kbit/s") % kbps
    return _("%.1f Mbit/s") % (kbps / 1000)


def version_text() -> str:
    """The small line at the bottom right, "0.1.2 by TrenSoft". A number and a name: not a
    translated string."""
    return "%s by %s" % (__version__, DEVELOPER)


def event_to_accelerator(Gdk: Any, Gtk: Any, event: Any) -> Optional[str]:
    """The key combination of a GTK 3 key press, as an accelerator (``<Primary><Shift>F9``).
    ``None`` for a modifier alone (the user is still holding the combination together). The
    way GTK's own accelerator entry reads it: the shift the layout used to get the symbol
    (``!`` on a US keyboard) is not a modifier, a shift that did not change it is."""
    keymap = Gdk.Keymap.get_for_display(Gdk.Display.get_default())
    found, keyval, _group, _level, consumed = keymap.translate_keyboard_state(
        event.hardware_keycode, event.state, event.group
    )
    if not found:
        return None
    lower = Gdk.keyval_to_lower(keyval)
    if lower == Gdk.KEY_ISO_Left_Tab:
        lower = Gdk.KEY_Tab
    name = Gdk.keyval_name(lower)
    if not name or name in _MODIFIER_KEYS:
        return None
    mask = event.state & Gtk.accelerator_get_default_mod_mask() & ~consumed
    if lower != keyval:
        mask |= Gdk.ModifierType.SHIFT_MASK
    text = ""
    for flag, modifier in (
        (Gdk.ModifierType.CONTROL_MASK, "Primary"),
        (Gdk.ModifierType.SHIFT_MASK, "Shift"),
        (Gdk.ModifierType.MOD1_MASK, "Alt"),
        (Gdk.ModifierType.SUPER_MASK, "Super"),
    ):
        if mask & flag:
            text += "<%s>" % modifier
    return canonical_accelerator(text + name)


class SettingsWindow:
    """One open window; ``closed`` says it was closed (the dot then opens a new one)."""

    def __init__(
        self,
        Gtk: Any,
        shortcuts: Callable[[], Shortcuts],
        installer: Callable[[], Shortcuts],
        event_to_keys: EventToKeys,
        on_saved: Callable[[], None] = lambda: None,
        icon_name: Optional[str] = None,
        grab: Callable[[Any], None] = lambda _window: None,
        release: Callable[[], None] = lambda: None,
        load_config: Callable[[], config.Config] = config.default_config,
        write_config: Callable[[Dict[str, str]], None] = config.set_values,
        choose_folder: ChooseFolder = lambda _window, _title, _current: None,
        confirm: Confirm = lambda _window, _question: False,
        video_codecs: Callable[[], FrozenSet[str]] = lambda: frozenset(),
    ) -> None:
        self._Gtk = Gtk
        self._shortcuts = shortcuts  # reads the keys now
        self._installer = installer  # writes them: needs to know the command the keys run
        self._event_to_keys = event_to_keys
        self._on_saved = on_saved  # called when the keys changed: the menu shows them
        self._grab = grab
        self._release = release
        self._load_config = load_config
        self._write_config = write_config
        self._choose_folder = choose_folder
        self._confirm = confirm
        self.h265_possible = "h265" in video_codecs()
        self.cfg = load_config()
        self.closed = False
        self.waiting: Optional[str] = None  # the slug whose new keys are awaited
        self.applying = False  # True while the controls are set from the settings, not by a person
        self.keys: Dict[str, str] = self._current_keys()
        self.buttons: Dict[str, Any] = {}
        self.folder_labels: Dict[str, Any] = {}
        self.folder_buttons: Dict[str, Any] = {}
        self.sliders: Dict[str, Any] = {}  # by settings key
        self.slider_texts: Dict[str, Any] = {}
        self.codec_buttons: Dict[str, Any] = {}  # video codec, by settings value
        self.container_buttons: Dict[str, Any] = {}
        self.audio_codec_box: Any = None

        window = Gtk.Window(title=_("Settings"))
        window.set_resizable(False)
        window.set_border_width(12)
        if icon_name:
            window.set_icon_name(icon_name)
        window.connect("destroy", self._destroyed)
        window.connect("key-press-event", self._key_pressed)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        window.add(box)
        self._build_keys(box)
        self._build_video(box)
        self._build_sound(box)
        self._build_folders(box)

        self.message = Gtk.Label(label="")
        self.message.set_xalign(0)
        self.message.set_line_wrap(True)
        self.message.set_selectable(True)
        box.pack_start(self.message, False, False, 0)

        bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.reset_button = Gtk.Button(label=_("Reset to defaults"))
        self.reset_button.connect("clicked", self._reset)
        self.close_button = Gtk.Button(label=_("Close"))
        self.close_button.connect("clicked", lambda *_args: self.window.destroy())
        version = Gtk.Label(label=version_text(), xalign=1, valign=Gtk.Align.END)
        version.set_selectable(True)
        version.get_style_context().add_class("dim-label")
        bottom.pack_start(self.reset_button, False, False, 0)
        bottom.pack_start(self.close_button, False, False, 0)
        bottom.pack_end(version, False, False, 0)
        box.pack_start(bottom, False, False, 6)
        self.window = window
        self.show_config()
        window.show_all()
        self._show_notes()  # after show_all, which shows every label; the notes decide themselves

    # -- building ------------------------------------------------------------------------------

    def _heading(self, box: Any, text: str) -> None:
        label = self._Gtk.Label(label=text)
        label.set_xalign(0)
        label.get_style_context().add_class("heading")
        box.pack_start(label, False, False, 4)

    def _note(self, box: Any, text: str) -> Any:
        """A line of explanation under a control; shown or hidden by ``_show_notes``."""
        label = self._Gtk.Label(label=text)
        label.set_xalign(0)
        label.set_line_wrap(True)
        label.set_max_width_chars(48)
        label.set_no_show_all(True)
        label.get_style_context().add_class("dim-label")
        box.pack_start(label, False, False, 0)
        return label

    def _row_label(self, text: str) -> Any:
        label = self._Gtk.Label(label=text)
        label.set_xalign(0)
        label.set_hexpand(True)
        return label

    def _build_keys(self, box: Any) -> None:
        Gtk = self._Gtk
        self._heading(box, _("Keyboard shortcuts"))
        hint = Gtk.Label(label=_("Click a field, then press the new keys. Escape cancels."))
        hint.set_xalign(0)
        hint.set_line_wrap(True)
        box.pack_start(hint, False, False, 0)
        grid = Gtk.Grid(column_spacing=12, row_spacing=6)
        names = shortcut_names()
        for row, shortcut in enumerate(SHORTCUTS):
            button = Gtk.Button(label=accelerator_label(self.keys[shortcut.slug]))
            button.connect("clicked", self._clicked, shortcut.slug)
            grid.attach(self._row_label(names[shortcut.slug]), 0, row, 1, 1)
            grid.attach(button, 1, row, 1, 1)
            self.buttons[shortcut.slug] = button
        box.pack_start(grid, False, False, 0)

    def _slider(self, grid: Any, row: int, text: str, key: str, steps: Sequence[int]) -> None:
        """A label, a slider over ``steps`` (its position is the index of a step), the value."""
        Gtk = self._Gtk
        adjustment = Gtk.Adjustment(value=0, lower=0, upper=len(steps) - 1, step_increment=1)
        scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=adjustment)
        scale.set_draw_value(False)
        scale.set_digits(0)
        scale.set_hexpand(True)
        scale.set_size_request(220, -1)
        scale.connect("value-changed", self._slid, key, steps)
        text_label = Gtk.Label(label="")
        text_label.set_xalign(1)
        text_label.set_width_chars(11)
        grid.attach(self._row_label(text), 0, row, 1, 1)
        grid.attach(scale, 1, row, 1, 1)
        grid.attach(text_label, 2, row, 1, 1)
        self.sliders[key] = scale
        self.slider_texts[key] = text_label

    def _radios(
        self, grid: Any, row: int, text: str, choices: Any, store: Dict[str, Any], key: str
    ):
        """A label and one radio button per choice, in a row."""
        Gtk = self._Gtk
        line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        first = None
        for value, name in choices:
            button = Gtk.RadioButton.new_with_label_from_widget(first, name)
            first = first or button
            button.connect("toggled", self._chose, key, value)
            line.pack_start(button, False, False, 0)
            store[value] = button
        grid.attach(self._row_label(text), 0, row, 1, 1)
        grid.attach(line, 1, row, 2, 1)

    def _build_video(self, box: Any) -> None:
        Gtk = self._Gtk
        self._heading(box, _("Video"))
        grid = Gtk.Grid(column_spacing=12, row_spacing=6)
        self._radios(
            grid,
            0,
            _("Video codec"),
            (
                ("h264", _("H.264 (plays everywhere)")),
                ("h265", _("H.265 (about half the file size)")),
            ),
            self.codec_buttons,
            "VIDEO_CODEC",
        )
        self.codec_buttons["h265"].set_sensitive(self.h265_possible)
        self._slider(grid, 1, _("Video bitrate"), "VIDEO_KBPS", VIDEO_BITRATE_STEPS)
        self._slider(grid, 2, _("Frame rate"), "FPS", FPS_STEPS)
        self._radios(
            grid,
            3,
            _("Video file format"),
            CONTAINER_NAMES,
            self.container_buttons,
            "CONTAINER",
        )
        box.pack_start(grid, False, False, 0)
        self.h265_missing_note = self._note(
            box, _("H.265 is not available: the graphics card cannot encode it.")
        )
        self.h265_play_note = self._note(
            box, _("H.265 videos may need an extra codec to play on Windows and in some browsers.")
        )

    def _build_sound(self, box: Any) -> None:
        Gtk = self._Gtk
        self._heading(box, _("Sound"))
        grid = Gtk.Grid(column_spacing=12, row_spacing=6)
        combo = Gtk.ComboBoxText()
        for value, name in AUDIO_CODEC_NAMES:
            combo.append(value, name)
        combo.connect("changed", self._combo_changed, "AUDIO_CODEC")
        grid.attach(self._row_label(_("Sound codec for sound-only recordings")), 0, 0, 1, 1)
        grid.attach(combo, 1, 0, 2, 1)
        self.audio_codec_box = combo
        self._slider(grid, 1, _("Sound bitrate with video"), "AAC_KBPS", SOUND_BITRATE_STEPS)
        self._slider(
            grid, 2, _("Sound bitrate for sound-only recordings"), "MP3_KBPS", SOUND_BITRATE_STEPS
        )
        box.pack_start(grid, False, False, 0)
        self.sound_note = self._note(
            box,
            _("Applies only to sound-only recordings. With video, the sound is always AAC."),
        )

    def _build_folders(self, box: Any) -> None:
        Gtk = self._Gtk
        self._heading(box, _("Folders"))
        grid = Gtk.Grid(column_spacing=12, row_spacing=6)
        names = {"video": _("Videos are saved in"), "audio": _("Sound recordings are saved in")}
        for row, (kind, _key) in enumerate(FOLDER_KEYS):
            path = Gtk.Label(label="")
            path.set_xalign(0)
            path.set_selectable(True)
            path.set_max_width_chars(36)
            choose = Gtk.Button(label=_("Choose…"))
            choose.connect("clicked", self._folder_clicked, kind)
            grid.attach(self._row_label(names[kind]), 0, row, 1, 1)
            grid.attach(path, 1, row, 1, 1)
            grid.attach(choose, 2, row, 1, 1)
            self.folder_labels[kind] = path
            self.folder_buttons[kind] = choose
        box.pack_start(grid, False, False, 6)

    # -- showing the settings ------------------------------------------------------------------

    def show_config(self) -> None:
        """Set every control to ``self.cfg``. Not a change by a person: nothing is written."""
        self.applying = True
        try:
            cfg = self.cfg
            self.codec_buttons[cfg.video_codec].set_active(True)
            self.container_buttons[cfg.container].set_active(True)
            self.audio_codec_box.set_active_id(cfg.audio_codec)
            for key, steps, value in (
                ("VIDEO_KBPS", VIDEO_BITRATE_STEPS, cfg.video_kbps),
                ("FPS", FPS_STEPS, cfg.fps),
                ("AAC_KBPS", SOUND_BITRATE_STEPS, cfg.aac_kbps),
                ("MP3_KBPS", SOUND_BITRATE_STEPS, cfg.mp3_kbps),
            ):
                self.sliders[key].set_value(nearest_step(steps, value))
                self.slider_texts[key].set_text(self._value_text(key, value))
            for kind, _key in FOLDER_KEYS:
                self._show_folder(kind)
        finally:
            self.applying = False
        self._show_notes()

    @staticmethod
    def _value_text(key: str, value: int) -> str:
        return _("%d fps") % value if key == "FPS" else rate_text(value)

    def _show_notes(self) -> None:
        cfg = self.cfg
        self.h265_missing_note.set_visible(not self.h265_possible)
        self.h265_play_note.set_visible(self.h265_possible and cfg.video_codec == "h265")
        self.sound_note.set_visible(cfg.audio_codec != "aac")

    def _folder_text(self, kind: str) -> str:
        """The folder of a kind as the row shows it: the real path."""
        written = self.cfg.video_folder if kind == "video" else self.cfg.audio_folder
        return config.expand(written or self.cfg.folder)

    def _show_folder(self, kind: str) -> None:
        text = self._folder_text(kind)
        self.folder_labels[kind].set_text(text)
        self.folder_labels[kind].set_tooltip_text(text)

    # -- the settings file ---------------------------------------------------------------------

    def _current_keys(self) -> Dict[str, str]:
        """What the entries have now; the default keys where there is nothing (yet)."""
        try:
            now = self._shortcuts().bindings()
        except ShortcutError as error:
            _LOG.warning("[settings] cannot read the shortcuts: %s", error)
            now = {}
        return {s.slug: now.get(s.slug) or s.accelerator for s in SHORTCUTS}

    def _write(self, updates: Dict[str, str]) -> bool:
        """Write settings. ``False`` (and the reason in the window) when that failed; the controls
        then show the file again, so they never say what the file does not."""
        try:
            self._write_config(updates)
        except (OSError, ValueError) as error:
            _LOG.error("[settings] cannot save %s: %s", ", ".join(updates), error)
            self._say(str(error))
            self.cfg = self._load_config()
            self.show_config()
            return False
        self.cfg = self._load_config()
        self._say("")
        return True

    def _slid(self, scale: Any, key: str, steps: Sequence[int]) -> None:
        if self.applying:
            return
        value = steps[int(round(scale.get_value()))]
        self.slider_texts[key].set_text(self._value_text(key, value))
        self._write({key: str(value)})  # a failure shows the file's value again

    def _chose(self, button: Any, key: str, value: str) -> None:
        """A radio button toggled: only the one that became active is a choice."""
        if self.applying or not button.get_active():
            return
        if self._write({key: value}):
            self._show_notes()

    def _combo_changed(self, combo: Any, key: str) -> None:
        value = combo.get_active_id()
        if self.applying or not value:
            return
        if self._write({key: value}):
            self._show_notes()

    # -- window --------------------------------------------------------------------------------

    def present(self) -> None:
        self.window.present()

    def _destroyed(self, *_args: Any) -> None:
        self.closed = True
        if self.waiting is not None:
            self.waiting = None
            self._release()

    def _say(self, text: str) -> None:
        self.message.set_text(text)

    def _show_keys(self, slug: str) -> None:
        self.buttons[slug].set_label(accelerator_label(self.keys[slug]))

    # -- folders -------------------------------------------------------------------------------

    def _folder_clicked(self, _button: Any, kind: str) -> None:
        self._stop_waiting()
        chosen = self._choose_folder(self.window, _("Choose a folder"), self._folder_text(kind))
        if not chosen:
            return
        written = config.portable(chosen)
        same = config.expand(written) == config.expand(self.cfg.folder)
        key = dict(FOLDER_KEYS)[kind]
        if self._write({key: "" if same else written}):
            self._show_folder(kind)

    # -- keys ----------------------------------------------------------------------------------

    def _stop_waiting(self) -> None:
        if self.waiting is not None:
            slug, self.waiting = self.waiting, None
            self._release()
            self._show_keys(slug)

    def _clicked(self, _button: Any, slug: str) -> None:
        self._stop_waiting()
        self.waiting = slug
        self._grab(self.window)  # the keys of the desktop (Ctrl+Shift+F9) must reach this window
        self._say("")
        self.buttons[slug].set_label(_("Press the keys..."))

    def _key_pressed(self, _window: Any, event: Any) -> bool:
        if self.waiting is None:
            return False  # not ours: Tab, Enter and the rest work as in any window
        keys = self._event_to_keys(event)
        if keys is None:
            return True  # a modifier on its way to a combination
        if keys == "Escape":
            self._stop_waiting()
            return True
        if accelerator_problem(keys) == "modifier":
            self._say(_("Use Ctrl, Alt or Super together with the key."))
            return True
        slug, self.waiting = self.waiting, None
        self._release()
        self._set_keys(slug, keys)
        return True

    @staticmethod
    def duplicates(keys: Mapping[str, str]) -> List[str]:
        """The slugs whose keys another one of ours has too."""
        values = list(keys.items())
        return [
            slug
            for slug, accelerator in values
            if any(o != slug and same_accelerator(accelerator, k) for o, k in values)
        ]

    def _set_keys(self, slug: str, accelerator: str) -> None:
        """Make ``accelerator`` the keys of ``slug``, now. A refusal (two of ours with the same
        keys, a key another program has, GNOME's settings missing) is said in the window and the
        row goes back to the keys it had."""
        candidate = {**self.keys, slug: accelerator}
        if self.duplicates(candidate):
            self._say(_("Two of the shortcuts have the same keys."))
            self._show_keys(slug)
            return
        try:
            self._installer().install(candidate)
        except ShortcutError as error:
            _LOG.error("[settings] %s", error)
            self._say("%s: %s" % (_("Could not set the keyboard shortcuts"), error))
            self._show_keys(slug)
            return
        self.keys = candidate
        self._show_keys(slug)
        self._say("")
        self._on_saved()

    # -- reset ---------------------------------------------------------------------------------

    def _reset(self, _button: Any = None) -> None:
        """After a yes: every setting out of the file (so each has its default again) and the six
        default keys back."""
        self._stop_waiting()
        if not self._confirm(self.window, _("Reset every setting to its default value?")):
            return
        if not self._write({key: "" for key in config.KEYS}):
            return
        self.show_config()  # the file has the defaults now; the controls follow
        defaults = {s.slug: s.accelerator for s in SHORTCUTS}
        try:
            self._installer().install(defaults)
        except ShortcutError as error:
            _LOG.error("[settings] %s", error)
            self._say("%s: %s" % (_("Could not set the keyboard shortcuts"), error))
            return
        self.keys = defaults
        for slug in defaults:
            self._show_keys(slug)
        self._on_saved()


_PROBED: Optional[FrozenSet[str]] = None


def _probed_codecs() -> FrozenSet[str]:
    """What the recorder can encode, asked once per process: the answer does not change while the
    dot runs, and asking takes a moment."""
    global _PROBED
    if _PROBED is None:
        _PROBED = codecs.video_codecs()
    return _PROBED


def open_window(
    Gtk: Any,
    Gdk: Any,
    shortcuts: Callable[[], Shortcuts],
    installer: Callable[[], Shortcuts],
    on_saved: Callable[[], None] = lambda: None,
    icon_name: Optional[str] = None,
) -> SettingsWindow:
    """The window for the real GTK 3 and Gdk."""

    def grab(window: Any) -> None:
        """Take the keyboard from the desktop while the keys are awaited, so that pressing a key
        the shell uses (the shortcut being changed) reaches the window instead of starting a
        recording. A courtesy: when the grab is refused the window still takes the keys it gets."""
        try:
            seat = Gdk.Display.get_default().get_default_seat()
            seat.grab(
                window.get_window(), Gdk.SeatCapabilities.KEYBOARD, False, None, None, None, None
            )
        except Exception as error:  # a grab never decides whether the window works
            _LOG.warning("[settings] cannot grab the keyboard: %s", error)

    def choose_folder(window: Any, title: str, current: str) -> Optional[str]:
        """The desktop's folder chooser (through the portal on GNOME); ``None`` when cancelled."""
        dialog = Gtk.FileChooserNative.new(
            title, window, Gtk.FileChooserAction.SELECT_FOLDER, None, None
        )
        try:
            dialog.set_modal(True)
            dialog.set_create_folders(True)
            if current and os.path.isdir(current):
                dialog.set_current_folder(current)
            if dialog.run() == Gtk.ResponseType.ACCEPT:
                return str(dialog.get_filename() or "") or None
            return None
        finally:
            dialog.destroy()

    def confirm(window: Any, question: str) -> bool:
        """A yes/no question in a dialog of the desktop; the buttons are GTK's own (translated by
        GTK). Anything but OK is no."""
        dialog = Gtk.MessageDialog(
            transient_for=window,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text=question,
        )
        try:
            return bool(dialog.run() == Gtk.ResponseType.OK)
        finally:
            dialog.destroy()

    def release() -> None:
        try:
            Gdk.Display.get_default().get_default_seat().ungrab()
        except Exception as error:
            _LOG.warning("[settings] cannot release the keyboard: %s", error)

    return SettingsWindow(
        Gtk,
        shortcuts,
        installer,
        lambda event: event_to_accelerator(Gdk, Gtk, event),
        on_saved,
        icon_name,
        grab,
        release,
        lambda: config.load()[0],
        config.set_values,
        choose_folder,
        confirm,
        _probed_codecs,
    )
