# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

"""The dot in the top bar while a recording runs: red = recording, yellow = paused.

The menu has Pause/Resume and Stop and save. The process lives as long as the recording does:
when the state says nothing is recording any more (stopped, or the recorder died), it quits.
It needs the AppIndicator extension of GNOME Shell for the dot to show.

GTK 3 and an AppIndicator library are loaded when the dot starts, not at import, so everything
else in Hotrec (and the tests) works without them. Two libraries provide the same API; the
Ayatana one is tried first.
"""

from __future__ import annotations

import fcntl
import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Tuple

from hotrec import APP_ID, _
from hotrec.recorder import Recorder, State

_LOG = logging.getLogger(__name__)

ICON_RECORDING = APP_ID + "-recording"
ICON_PAUSED = APP_ID + "-paused"
REFRESH_MILLISECONDS = 500


@dataclass(frozen=True)
class View:
    icon: str
    description: str  # the accessible description of the icon
    pause_label: str  # the text of the first menu item


def view(state: Optional[State]) -> Optional[View]:
    """What the dot looks like for a state; ``None`` means the dot should go away."""
    if state is None:
        return None
    if state.paused:
        return View(ICON_PAUSED, _("Paused"), _("Resume"))
    return View(ICON_RECORDING, _("Recording"), _("Pause"))


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


def run(recorder: Optional[Recorder] = None, toolkit: Optional[Tuple[Any, Any, Any]] = None) -> int:
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
        return 0

    indicator = AppIndicator.Indicator.new(
        APP_ID, first.icon, AppIndicator.IndicatorCategory.APPLICATION_STATUS
    )
    theme = icon_theme_dir()
    if theme:
        indicator.set_icon_theme_path(theme)
    indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)

    menu = Gtk.Menu()
    pause_item = Gtk.MenuItem(label=first.pause_label)
    stop_item = Gtk.MenuItem(label=_("Stop and save"))
    pause_item.connect("activate", lambda *_args: _spawn("pause"))
    stop_item.connect("activate", lambda *_args: _spawn("stop"))
    menu.append(pause_item)
    menu.append(stop_item)
    menu.show_all()
    indicator.set_menu(menu)

    def refresh() -> bool:
        current = view(recorder.status())
        if current is None:
            Gtk.main_quit()
            return False
        indicator.set_icon_full(current.icon, current.description)
        pause_item.set_label(current.pause_label)
        return True

    GLib.timeout_add(REFRESH_MILLISECONDS, refresh)
    Gtk.main()
    return 0
