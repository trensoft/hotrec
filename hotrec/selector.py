# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

"""The window where the area to record is drawn with the mouse (``hotrec select-region``).

GNOME on Wayland has no tool for this (no ``slurp``), so Hotrec draws its own: on every monitor a
transparent fullscreen GTK 3 window dims the screen; a drag with the left button draws the area,
releasing the button chooses it. Escape or the right button gives up. The area is printed on the
standard output as JSON (``region.Region``: fractions of the monitor it was drawn on), the exit
status is 0 for a choice and ``SELECT_CANCELLED`` for giving up, so the recorder can run this as
a process of its own and GTK is loaded only here.

``DragSelection`` is the logic of one window (a drag, the rectangle to paint), without GTK; the
rest of this module is the thin GTK 3 part around it.
"""

from __future__ import annotations

import logging
import sys
from typing import Any, Optional, Tuple

from hotrec import _
from hotrec.recorder import SELECT_CANCELLED
from hotrec.region import Region, region_from_drag

_LOG = logging.getLogger(__name__)

DIM = 0.45  # how dark the screen is outside the area


class DragSelection:
    """One window's mouse drag. ``press`` starts it, ``motion`` follows it, ``release`` ends it
    and returns the area when the drag was big enough (else the drag is forgotten and the user
    can draw again)."""

    def __init__(self, width: float, height: float) -> None:
        self.width = width
        self.height = height
        self.start: Optional[Tuple[float, float]] = None
        self.end: Optional[Tuple[float, float]] = None

    def press(self, x: float, y: float) -> None:
        self.start = self.end = (x, y)

    def motion(self, x: float, y: float) -> None:
        if self.start is not None:
            self.end = (x, y)

    def release(self, x: float, y: float) -> Optional[Region]:
        if self.start is None:
            return None
        start, self.start, self.end = self.start, None, None
        return region_from_drag(start[0], start[1], x, y, self.width, self.height)

    def rectangle(self) -> Optional[Tuple[float, float, float, float]]:
        """``(x, y, width, height)`` of the drag so far, inside the window, to paint; ``None``
        when no drag is running."""
        if self.start is None or self.end is None:
            return None
        left, right = sorted((self.start[0], self.end[0]))
        top, bottom = sorted((self.start[1], self.end[1]))
        left, top = max(left, 0.0), max(top, 0.0)
        right, bottom = min(right, self.width), min(bottom, self.height)
        return left, top, max(right - left, 0.0), max(bottom - top, 0.0)


def _load_toolkit() -> Tuple[Any, Any]:
    import gi  # type: ignore[import-not-found]

    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, Gtk  # type: ignore

    return Gtk, Gdk


def run(toolkit: Optional[Tuple[Any, Any]] = None) -> int:
    """Show the windows and wait for the choice. Prints the area; returns the exit status."""
    try:
        Gtk, Gdk = toolkit or _load_toolkit()
    except (ImportError, ValueError) as error:
        print("hotrec: the area window needs GTK 3 (%s)" % error, file=sys.stderr)
        return 1
    display = Gdk.Display.get_default()
    if display is None or display.get_n_monitors() < 1:
        print("hotrec: no screen to draw on", file=sys.stderr)
        return 1
    outcome = {"code": SELECT_CANCELLED, "done": 0}

    def finish(code: int) -> None:
        if outcome["done"]:  # the first answer counts (closing the windows calls this again)
            return
        outcome["done"] = 1
        outcome["code"] = code
        Gtk.main_quit()

    for index in range(display.get_n_monitors()):
        _open_window(Gtk, Gdk, display, index, finish)
    Gtk.main()
    return outcome["code"]


def _open_window(Gtk: Any, Gdk: Any, display: Any, index: int, finish: Any) -> None:
    window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
    window.set_decorated(False)
    window.set_app_paintable(True)
    window.set_skip_taskbar_hint(True)
    window.set_keep_above(True)
    screen = window.get_screen()
    visual = screen.get_rgba_visual()
    if visual is not None:
        window.set_visual(visual)
    window.add_events(
        Gdk.EventMask.BUTTON_PRESS_MASK
        | Gdk.EventMask.BUTTON_RELEASE_MASK
        | Gdk.EventMask.POINTER_MOTION_MASK
        | Gdk.EventMask.KEY_PRESS_MASK
    )
    drag = DragSelection(1.0, 1.0)
    hint = _("Drag the area to record. Esc or the right button cancels.")

    def size() -> Tuple[float, float]:
        return float(window.get_allocated_width()), float(window.get_allocated_height())

    def draw(_widget: Any, cr: Any) -> bool:
        width, height = size()
        try:
            import cairo  # type: ignore[import-not-found]

            cr.set_operator(cairo.Operator.SOURCE)
            cr.set_source_rgba(0, 0, 0, 0)
            cr.paint()
            cr.set_operator(cairo.Operator.OVER)
        except ImportError:
            pass
        rectangle = drag.rectangle()
        cr.set_source_rgba(0, 0, 0, DIM)
        if rectangle is None:
            cr.rectangle(0, 0, width, height)
            cr.fill()
            cr.set_source_rgba(1, 1, 1, 0.95)
            cr.set_font_size(22)
            extents = cr.text_extents(hint)
            cr.move_to((width - extents.width) / 2, height / 2)
            cr.show_text(hint)
            return True
        x, y, w, h = rectangle
        for band in (
            (0, 0, width, y),
            (0, y + h, width, height - y - h),
            (0, y, x, h),
            (x + w, y, width - x - w, h),
        ):
            cr.rectangle(*band)
        cr.fill()
        cr.set_source_rgba(1, 0.15, 0.15, 1)
        cr.set_line_width(2)
        cr.rectangle(x, y, w, h)
        cr.stroke()
        return True

    def pressed(_widget: Any, event: Any) -> bool:
        if event.button == 3:
            finish(SELECT_CANCELLED)
        elif event.button == 1:
            drag.width, drag.height = size()
            drag.press(event.x, event.y)
            window.queue_draw()
        return True

    def moved(_widget: Any, event: Any) -> bool:
        drag.motion(event.x, event.y)
        window.queue_draw()
        return True

    def released(_widget: Any, event: Any) -> bool:
        if event.button != 1:
            return True
        area = drag.release(event.x, event.y)
        if area is None:
            window.queue_draw()
            return True
        print(area.to_json())
        sys.stdout.flush()
        finish(0)
        return True

    def key_pressed(_widget: Any, event: Any) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            finish(SELECT_CANCELLED)
        return True

    def realized(widget: Any) -> None:
        gdk_window = widget.get_window()
        if gdk_window is not None:
            gdk_window.set_cursor(Gdk.Cursor.new_from_name(display, "crosshair"))

    window.connect("draw", draw)
    window.connect("button-press-event", pressed)
    window.connect("motion-notify-event", moved)
    window.connect("button-release-event", released)
    window.connect("key-press-event", key_pressed)
    window.connect("realize", realized)
    window.connect("destroy", lambda *_args: finish(SELECT_CANCELLED))
    window.fullscreen_on_monitor(screen, index)
    window.show_all()
    window.present()
