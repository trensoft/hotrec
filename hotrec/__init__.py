# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

"""Hotrec: screen and sound recorder for GNOME on Wayland, driven by keyboard shortcuts.

``APP_ID`` is the one identity constant: the launcher file name, the AppStream id, the icon names
and the gettext domain all derive from it. Every string shown to a user goes through ``_()``
inside a function (``tools/i18n.sh check`` enforces it), so the catalogs can translate it.
"""

import gettext

_ = gettext.gettext

APP_ID = "io.github.trensoft.hotrec"
APP_NAME = "Hotrec"
__version__ = "0.1.0"
