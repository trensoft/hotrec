# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

"""The GNOME Shell extension that shows the recording dot over a fullscreen video.

The tray dot cannot be seen when a fullscreen window covers the top bar. The package
``hotrec-gnome-shell-extension`` has an extension (``gnome-shell/hotrec-dot@...``) that draws a dot
above everything, from the state file Hotrec keeps while it records. Hotrec only has to get the
extension switched on, once per user: ``offer`` (called by ``hotrec autostart`` at login) adds it to
the GSettings key ``org.gnome.shell enabled-extensions`` when the package is installed, and says so
in one notification. A running Shell learns about a new extension only at the next login: when the
package came after the login the notification says so, but when the package was already there the
Shell knows the extension, takes the new setting at once, and the notification asks for nothing.

Once means once: the file ``offered_marker`` records that it was done (or that the user had the
extension disabled on purpose), so an extension the user turns off in the Extensions app is not
turned on again at every login. Removing that file offers it again.

``gsettings`` and ``gdbus`` are run through ``run`` so the tests can answer for them.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
from pathlib import Path
from typing import List, Mapping, Optional

from hotrec import APP_NAME, _, __version__
from hotrec.shortcuts import Run, ShortcutError, _run, done_marker, gvariant_list, parse_list

_LOG = logging.getLogger(__name__)

UUID = "hotrec-dot@trensoft.github.io"
SCHEMA = "org.gnome.shell"
ENABLED_KEY = "enabled-extensions"
DISABLED_KEY = "disabled-extensions"

# org.gnome.Shell.Extensions.GetExtensionInfo answers an empty dictionary for an extension the
# running Shell does not know; otherwise it has the ``state`` (the ExtensionState number).
SHELL_EXTENSIONS = [
    "gdbus", "call", "--session",
    "--dest", "org.gnome.Shell.Extensions",
    "--object-path", "/org/gnome/Shell/Extensions",
    "--method", "org.gnome.Shell.Extensions.GetExtensionInfo",
]  # fmt: skip
# ENABLED, DISABLED, INITIALIZED, DISABLING, ENABLING: loaded and usable (not ERROR, OUT_OF_DATE,
# DOWNLOADING or UNINSTALLED)
LOADED_STATES = {1, 2, 6, 7, 8}


def offered_marker(env: Optional[Mapping[str, str]] = None) -> Path:
    """The file that says the extension was offered: next to the shortcuts' ``done_marker``."""
    return done_marker(env).with_name("dot-extension-offered")


def extension_dirs(env: Optional[Mapping[str, str]] = None) -> List[Path]:
    """Where GNOME Shell looks for extensions: the user's and then the system's data directories."""
    env = os.environ if env is None else env
    home = Path(env.get("HOME") or "~").expanduser()
    data_home = env.get("XDG_DATA_HOME")
    roots = [Path(data_home) if data_home and os.path.isabs(data_home) else home / ".local/share"]
    data_dirs = env.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    roots += [Path(d) for d in data_dirs.split(":") if d and os.path.isabs(d)]
    return [root / "gnome-shell" / "extensions" / UUID for root in roots]


def installed(env: Optional[Mapping[str, str]] = None) -> bool:
    """Whether the extension is on this computer (the package, or a copy of the user's own)."""
    return any((path / "metadata.json").is_file() for path in extension_dirs(env))


def _get_list(run: Run, key: str) -> List[str]:
    code, out = run(["gsettings", "get", SCHEMA, key])
    if code != 0:
        raise ShortcutError("gsettings get %s %s: %s" % (SCHEMA, key, out.strip()))
    return parse_list(out)


def shell_knows(run: Run = _run, which=shutil.which) -> bool:
    """Whether the running Shell has loaded the extension: then a change of ``enabled-extensions``
    switches it on at once. False when it does not (the package came after the login), when it is
    broken or out of date, or when the Shell cannot be asked: the safe answer is "log out and in".
    """
    if not which("gdbus"):
        return False
    code, out = run(SHELL_EXTENSIONS + [UUID])
    if code != 0 or UUID not in out:
        return False
    state = re.search(r"'state': <(?:double |uint32 |int32 )?(\d+)", out)
    return bool(state) and int(state.group(1)) in LOADED_STATES


def _remember(env: Optional[Mapping[str, str]]) -> None:
    marker = offered_marker(env)
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("%s\n" % __version__, encoding="utf-8")
    except OSError as problem:
        _LOG.warning("[dot-extension] cannot write %s: %s", marker, problem)


def offer(
    notify,
    env: Optional[Mapping[str, str]] = None,
    run: Run = _run,
    which=shutil.which,
) -> bool:
    """Switch the extension on for this user the first time it is seen. ``notify(summary, body)``
    tells the user. Returns whether it was switched on now.

    Nothing happens when it was offered before (the marker), when the package is not installed (it
    may come later: no marker), or when ``gsettings`` does not answer (tried again at the next
    login). An extension the user has in ``disabled-extensions``, or already enabled, is left as it
    is, and counts as offered."""
    if offered_marker(env).exists() or not installed(env) or not which("gsettings"):
        return False
    try:
        enabled = _get_list(run, ENABLED_KEY)
        disabled = _get_list(run, DISABLED_KEY)
    except ShortcutError as error:
        _LOG.warning("[dot-extension] %s", error)
        return False
    if UUID in enabled or UUID in disabled:
        _remember(env)
        return False
    known = shell_knows(run, which)  # asked before the change: it is what decides the text
    code, out = run(["gsettings", "set", SCHEMA, ENABLED_KEY, gvariant_list(enabled + [UUID])])
    if code != 0:
        _LOG.warning("[dot-extension] gsettings set %s %s: %s", SCHEMA, ENABLED_KEY, out.strip())
        return False
    _remember(env)
    if known:
        text = _(
            "The blinking red dot over a fullscreen video is on. "
            "You can turn it off in the Extensions app."
        )
    else:
        text = _(
            "The blinking red dot over a fullscreen video is on. "
            "If you do not see it yet, log out and in once. "
            "You can turn it off in the Extensions app."
        )
    notify(APP_NAME, text)
    return True
