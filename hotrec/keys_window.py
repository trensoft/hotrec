# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

"""The window where the four keyboard shortcuts are chosen (menu of the top bar dot).

Four rows, one per shortcut: its name and a button with the keys it has. A click on the button
waits for the new keys ("Press the keys..."), Escape gives that up. Save writes them into the
GNOME custom keybindings with ``Shortcuts.install``, the same code ``hotrec setup`` uses: a key
that another program's custom keybinding already has is refused (and said so), nothing of other
programs is overwritten. At the bottom right the version and the maker, as in the settings
window of Slideshow Lock ("0.1.2 by TrenSoft").

The window shows the keys the entries have now; shortcuts that are not installed yet show the
default keys (Ctrl+Shift+F9 to F12), which is what Save would set.

GTK 3 is passed in (``indicator`` loads it when the dot starts); the Gdk part of reading a key
press is a separate function, so the logic runs under test without a display.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from hotrec import DEVELOPER, _, __version__
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


class KeysWindow:
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
    ) -> None:
        self._shortcuts = shortcuts  # reads the keys now
        self._installer = installer  # writes them: needs to know the command the keys run
        self._event_to_keys = event_to_keys
        self._on_saved = on_saved
        self._grab = grab
        self._release = release
        self.closed = False
        self.waiting: Optional[str] = None  # the slug whose new keys are awaited
        self.keys: Dict[str, str] = self._current_keys()
        self.buttons: Dict[str, Any] = {}

        window = Gtk.Window(title=_("Keyboard shortcuts"))
        window.set_resizable(False)
        window.set_border_width(12)
        if icon_name:
            window.set_icon_name(icon_name)
        window.connect("destroy", self._destroyed)
        window.connect("key-press-event", self._key_pressed)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        window.add(box)
        hint = Gtk.Label(label=_("Click a field, then press the new keys. Escape cancels."))
        hint.set_xalign(0)
        hint.set_line_wrap(True)
        box.pack_start(hint, False, False, 0)

        grid = Gtk.Grid(column_spacing=12, row_spacing=6)
        names = shortcut_names()
        for row, shortcut in enumerate(SHORTCUTS):
            label = Gtk.Label(label=names[shortcut.slug])
            label.set_xalign(0)
            label.set_hexpand(True)
            button = Gtk.Button(label=accelerator_label(self.keys[shortcut.slug]))
            button.connect("clicked", self._clicked, shortcut.slug)
            grid.attach(label, 0, row, 1, 1)
            grid.attach(button, 1, row, 1, 1)
            self.buttons[shortcut.slug] = button
        box.pack_start(grid, False, False, 0)

        self.message = Gtk.Label(label="")
        self.message.set_xalign(0)
        self.message.set_line_wrap(True)
        self.message.set_selectable(True)
        box.pack_start(self.message, False, False, 0)

        bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        save = Gtk.Button(label=_("Save"))
        save.connect("clicked", self._save)
        version = Gtk.Label(label=version_text(), xalign=1, valign=Gtk.Align.END)
        version.set_selectable(True)
        version.get_style_context().add_class("dim-label")
        bottom.pack_start(save, False, False, 0)
        bottom.pack_end(version, False, False, 0)
        box.pack_start(bottom, False, False, 6)
        self.window = window
        self.save_button = save
        window.show_all()

    def _current_keys(self) -> Dict[str, str]:
        """What the entries have now; the default keys where there is nothing (yet)."""
        try:
            now = self._shortcuts().bindings()
        except ShortcutError as error:
            _LOG.warning("[keys] cannot read the shortcuts: %s", error)
            now = {}
        return {s.slug: now.get(s.slug) or s.accelerator for s in SHORTCUTS}

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
        self.keys[slug] = keys
        self._show_keys(slug)
        self._say("")
        return True

    def duplicates(self) -> List[str]:
        """The slugs whose keys another one of ours has too."""
        values = list(self.keys.items())
        return [
            slug
            for slug, keys in values
            if any(o != slug and same_accelerator(keys, k) for o, k in values)
        ]

    def _save(self, _button: Any = None) -> None:
        self._stop_waiting()
        if self.duplicates():
            self._say(_("Two of the shortcuts have the same keys."))
            return
        try:
            self._installer().install(self.keys)
        except ShortcutError as error:
            _LOG.error("[keys] %s", error)
            self._say("%s: %s" % (_("Could not set the keyboard shortcuts"), error))
            return
        self._on_saved()
        self.window.destroy()


def open_window(
    Gtk: Any,
    Gdk: Any,
    shortcuts: Callable[[], Shortcuts],
    installer: Callable[[], Shortcuts],
    on_saved: Callable[[], None] = lambda: None,
    icon_name: Optional[str] = None,
) -> KeysWindow:
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
            _LOG.warning("[keys] cannot grab the keyboard: %s", error)

    def release() -> None:
        try:
            Gdk.Display.get_default().get_default_seat().ungrab()
        except Exception as error:
            _LOG.warning("[keys] cannot release the keyboard: %s", error)

    return KeysWindow(
        Gtk,
        shortcuts,
        installer,
        lambda event: event_to_accelerator(Gdk, Gtk, event),
        on_saved,
        icon_name,
        grab,
        release,
    )
