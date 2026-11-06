# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

"""The dot in the top bar while a recording runs: red and blinking = recording, yellow = paused.

The menu has Pause/Resume and Stop and save. Started by a recording, the process lives as long as
the recording does: when the state says nothing is recording any more (stopped, or the recorder
died), it quits. Started at login (``hotrec autostart``, ``resident=True``) it stays, shows the
Hotrec icon while nothing records, and has the ways to start a recording in its menu too. Each
command is one line with its keys as GNOME has them now ("Record screen and sound (Ctrl+Shift+F9)");
the resident one ends with "Settings..." (the window in ``settings_window``), "About" (the window
in ``about_window``) and "Quit" (a recording that runs is stopped and saved first, then the dot
goes; the next login starts it again as before). There is only ever one: a second one exits at
once. It needs the AppIndicator extension of GNOME Shell for the dot to show.

GTK 3 and an AppIndicator library are loaded when the dot starts, not at import, so everything
else in Hotrec (and the tests) works without them. Two libraries provide the same API; the
Ayatana one is tried first.
"""

from __future__ import annotations

import fcntl
import logging
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from hotrec import APP_ID, _, about_window, settings_window
from hotrec.recorder import MODES, Recorder, State
from hotrec.shortcuts import (
    SHORTCUTS,
    ShortcutError,
    Shortcuts,
    accelerator_label,
    shortcut_names,
)

_LOG = logging.getLogger(__name__)

ICON_RECORDING = APP_ID + "-recording"
ICON_RECORDING_OFF = APP_ID + "-recording-off"  # the dark half of the blinking red dot
ICON_PAUSED = APP_ID + "-paused"
ICON_IDLE = APP_ID + "-symbolic"
REFRESH_MILLISECONDS = 500  # also the blink: the red dot changes at every refresh
KEYS_REREAD_TICKS = 120  # the keys in the menu lines are read again every minute


@dataclass(frozen=True)
class View:
    icon: str
    description: str  # the accessible description of the icon
    pause_label: str  # the text of the first menu item


def view(state: Optional[State], lit: bool = True) -> Optional[View]:
    """What the dot looks like for a state; ``None`` means the dot should go away. A recording
    blinks: ``lit`` False is the dark half. A paused one does not blink."""
    if state is None:
        return None
    if state.paused:
        return View(ICON_PAUSED, _("Paused"), _("Resume"))
    return View(ICON_RECORDING if lit else ICON_RECORDING_OFF, _("Recording"), _("Pause"))


def idle_view() -> View:
    """The dot of a resident indicator while nothing records."""
    return View(ICON_IDLE, "Hotrec", _("Pause"))


def icon_theme_dir() -> Optional[str]:
    """``data/icons`` next to the package when running from a checkout; an installed copy finds
    its icons in the system theme, so there is nothing to add."""
    path = Path(__file__).resolve().parent.parent / "data" / "icons"
    return str(path) if path.is_dir() else None


def _load_toolkit() -> Tuple[Any, Any, Any]:
    import gi  # type: ignore[import-not-found]

    gi.require_version("Gtk", "3.0")
    try:
        gi.require_version("AyatanaAppIndicator3", "0.1")
        from gi.repository import AyatanaAppIndicator3 as AppIndicator  # type: ignore
    except (ValueError, ImportError):
        gi.require_version("AppIndicator3", "0.1")
        from gi.repository import AppIndicator3 as AppIndicator  # type: ignore
    from gi.repository import GLib, Gtk  # type: ignore

    return Gtk, GLib, AppIndicator


def _key_source() -> Shortcuts:
    """What reads the keys the shortcuts have now (the command is not used for reading)."""
    return Shortcuts("hotrec")


def _installer() -> Shortcuts:
    """What writes the keys: they run ``hotrec`` from the PATH, as ``hotrec setup`` does."""
    command = shutil.which("hotrec")
    if not command:
        raise ShortcutError("hotrec is not on the PATH")
    return Shortcuts(command)


def key_labels(source: Optional[Shortcuts] = None) -> Dict[str, Optional[str]]:
    """The keys of each shortcut as a person reads them ("Ctrl+Shift+F9"), from the keys as GNOME
    has them now; ``None`` for a shortcut that has no keys (or for all of them when they cannot
    be read: GNOME's settings are not there)."""
    try:
        bindings = (source or _key_source()).bindings()
    except ShortcutError as error:
        _LOG.info("cannot read the shortcuts: %s", error)
        return {s.slug: None for s in SHORTCUTS}
    return {
        s.slug: accelerator_label(bindings[s.slug]) if bindings.get(s.slug) else None
        for s in SHORTCUTS
    }


def with_keys(text: str, keys: Optional[str]) -> str:
    """A menu line: the command, and its keys in brackets when it has some."""
    return "%s (%s)" % (text, keys) if keys else text


def _spawn(*args: str) -> None:
    subprocess.Popen(
        [sys.executable, "-m", "hotrec", *args],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _single_instance(recorder: Recorder) -> Optional[Any]:
    """The open lock file of the one dot, or ``None`` when another dot has it."""
    handle = open(recorder.dir / "indicator.lock", "a")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def run(
    recorder: Optional[Recorder] = None,
    toolkit: Optional[Tuple[Any, Any, Any]] = None,
    resident: bool = False,
) -> int:
    recorder = recorder or Recorder()
    lock = _single_instance(recorder)
    if lock is None:
        return 0
    try:
        Gtk, GLib, AppIndicator = toolkit or _load_toolkit()
    except (ImportError, ValueError) as error:
        print(
            "hotrec: the top bar dot needs GTK 3 and an AppIndicator library (%s)" % error,
            file=sys.stderr,
        )
        return 1
    first = view(recorder.status())
    if first is None:
        if not resident:
            return 0
        first = idle_view()

    indicator = AppIndicator.Indicator.new(
        APP_ID, first.icon, AppIndicator.IndicatorCategory.APPLICATION_STATUS
    )
    theme = icon_theme_dir()
    if theme:
        indicator.set_icon_theme_path(theme)
    indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)

    menu = Gtk.Menu()
    names = shortcut_names()
    keys: Dict[str, Optional[str]] = {}
    start_items = []
    if resident:
        for mode in MODES:  # the modes are the shortcut slugs
            item = Gtk.MenuItem(label=with_keys(names[mode], None))
            item.connect("activate", lambda *_args, mode=mode: _spawn(mode))
            menu.append(item)
            start_items.append((mode, item))
    pause_item = Gtk.MenuItem(label=first.pause_label)
    stop_item = Gtk.MenuItem(label=_("Stop and save"))
    pause_item.connect("activate", lambda *_args: _spawn("pause"))
    stop_item.connect("activate", lambda *_args: _spawn("stop"))
    menu.append(pause_item)
    menu.append(stop_item)
    settings_item = about_item = quit_item = None
    if resident:
        menu.append(Gtk.SeparatorMenuItem())
        settings_item = Gtk.MenuItem(label=_("Settings…"))
        about_item = Gtk.MenuItem(label=_("About"))
        quit_item = Gtk.MenuItem(label=_("Quit"))
        menu.append(settings_item)
        menu.append(about_item)
        menu.append(quit_item)
    menu.show_all()
    indicator.set_menu(menu)

    shown: List[View] = [first]  # what the pause line says now, for show_keys

    def show_keys() -> None:
        keys.update(key_labels())
        for mode, item in start_items:
            item.set_label(with_keys(names[mode], keys.get(mode)))
        pause_item.set_label(with_keys(shown[0].pause_label, keys.get("pause")))

    settings = about = None

    def open_settings(*_args: Any) -> None:
        nonlocal settings
        if settings is not None and not settings.closed:
            settings.present()
            return
        import gi  # type: ignore[import-not-found]

        gi.require_version("Gdk", "3.0")
        from gi.repository import Gdk  # type: ignore

        settings = settings_window.open_window(Gtk, Gdk, _key_source, _installer, show_keys, APP_ID)

    def open_about(*_args: Any) -> None:
        nonlocal about
        if about is not None and not about.closed:
            about.present()
            return
        about = about_window.open_about(Gtk, APP_ID)

    if settings_item is not None and about_item is not None:
        settings_item.connect("activate", open_settings)
        about_item.connect("activate", open_about)

    def quit_dot(*_args: Any) -> None:
        """Stop and save what records, as ``Stop and save`` does, then end the process. The stop
        (which can cut an area out of a long recording) runs off the GTK thread. If a recording
        is still there afterwards the dot stays, so it is never left running without one."""
        if quit_item is None:
            return
        quit_item.set_sensitive(False)

        def stop_then_quit() -> None:
            try:
                recorder.stop()
                still_recording = recorder.status() is not None
            except Exception:  # the dot is not to die on a surprise of the recorder
                _LOG.exception("[quit] stopping the recording failed")
                still_recording = True
            if still_recording:
                _LOG.warning("[quit] a recording is still running: the dot stays")
                GLib.idle_add(quit_item.set_sensitive, True)
                return
            GLib.idle_add(finish_quit)

        threading.Thread(target=stop_then_quit, name="hotrec-quit").start()

    def finish_quit() -> bool:
        indicator.set_status(AppIndicator.IndicatorStatus.PASSIVE)
        Gtk.main_quit()
        return False

    if quit_item is not None:
        quit_item.connect("activate", quit_dot)

    def show(current: Optional[View]) -> None:
        recording = current is not None
        current = current or idle_view()
        indicator.set_icon_full(current.icon, current.description)
        shown[0] = current
        pause_item.set_label(with_keys(current.pause_label, keys.get("pause")))
        if resident:  # a recording is running: stop it or pause it; none: only start one
            pause_item.set_sensitive(recording)
            stop_item.set_sensitive(recording)
            for _mode, item in start_items:
                item.set_sensitive(not recording)

    ticks = 0

    def refresh() -> bool:
        nonlocal ticks
        ticks += 1
        if ticks % KEYS_REREAD_TICKS == 0:  # the keys can be changed in the GNOME settings too
            show_keys()
        current = view(recorder.status(), lit=ticks % 2 == 0)
        if current is None and not resident:
            Gtk.main_quit()
            return False
        show(current)
        return True

    show_keys()
    if resident:
        show(view(recorder.status()))
    GLib.timeout_add(REFRESH_MILLISECONDS, refresh)
    Gtk.main()
    return 0
