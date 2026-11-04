# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

"""The About window (last line of the menu of the top bar dot): the name, the version, a line
about the program, two links, the license and a Close button.

It is a small window of our own, not ``Gtk.AboutDialog``, so that every line is one of Hotrec's
translated strings in the language of the rest of the program (the dialog of GTK brings its own,
differently worded ones). The links are ``Gtk.LinkButton``: GTK opens them with the desktop's
browser. The version, the license id and the web addresses are not translated.

GTK 3 is passed in (``indicator`` loads it when the dot starts), so the logic runs under test
without a display.
"""

from __future__ import annotations

from typing import Any, Optional

from hotrec import APP_NAME, ISSUES_URL, LICENSE, WEBSITE, _, __version__


class AboutWindow:
    """One open window; ``closed`` says it was closed (the dot then opens a new one)."""

    def __init__(self, Gtk: Any, icon_name: Optional[str] = None) -> None:
        self.closed = False
        window = Gtk.Window(title=_("About"))
        window.set_resizable(False)
        window.set_border_width(18)
        if icon_name:
            window.set_icon_name(icon_name)
        window.connect("destroy", self._destroyed)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        window.add(box)
        if icon_name:
            box.pack_start(
                Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.DIALOG), False, False, 0
            )
        name = Gtk.Label(label=APP_NAME)
        name.get_style_context().add_class("title-1")
        box.pack_start(name, False, False, 0)
        box.pack_start(Gtk.Label(label=_("Version %s") % __version__), False, False, 0)
        about = Gtk.Label(
            label=_("Screen and sound recorder for GNOME, driven by keyboard shortcuts.")
        )
        about.set_line_wrap(True)
        about.set_max_width_chars(40)
        about.set_justify(Gtk.Justification.CENTER)
        box.pack_start(about, False, False, 6)
        self.links = [
            Gtk.LinkButton.new_with_label(WEBSITE, _("Website")),
            Gtk.LinkButton.new_with_label(ISSUES_URL, _("Report a problem")),
        ]
        for link in self.links:
            box.pack_start(link, False, False, 0)
        box.pack_start(Gtk.Label(label=_("License: %s") % LICENSE), False, False, 6)
        self.close_button = Gtk.Button(label=_("Close"))
        self.close_button.connect("clicked", lambda *_args: self.window.destroy())
        box.pack_start(self.close_button, False, False, 0)
        self.window = window
        window.show_all()

    def present(self) -> None:
        self.window.present()

    def _destroyed(self, *_args: Any) -> None:
        self.closed = True


def open_about(Gtk: Any, icon_name: Optional[str] = None) -> AboutWindow:
    """The window for the real GTK 3."""
    return AboutWindow(Gtk, icon_name)
