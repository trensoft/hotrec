# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

"""The four keyboard shortcuts, as GNOME custom keybindings.

GNOME on Wayland gives a program no global keys, so the keys are *the desktop's*: a custom
keybinding that runs ``hotrec <mode>``. They work in every window, which the keys of OBS do not
on Wayland. ``install`` adds ours to the list GNOME keeps in the GSettings key
``org.gnome.settings-daemon.plugins.media-keys custom-keybindings``, leaving the entries of other
programs alone; ``remove`` takes ours out again. Both are repeatable: running one twice changes
nothing the second time.

``gsettings`` is the interface (a program that has no GSettings schema of its own writes through
it). It is run through ``run`` so the tests can answer for it.
"""

from __future__ import annotations

import ast
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from hotrec import APP_ID, _

SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
LIST_KEY = "custom-keybindings"
ENTRY_SCHEMA = SCHEMA + ".custom-keybinding"
PATH_PREFIX = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/"


@dataclass(frozen=True)
class Shortcut:
    slug: str  # the last part of the dconf path, and the command argument
    accelerator: str  # GTK notation, what gsettings stores
    keys: str  # for people


SHORTCUTS = (
    Shortcut("video-audio", "<Primary><Shift>F9", "Ctrl+Shift+F9"),
    Shortcut("video", "<Primary><Shift>F10", "Ctrl+Shift+F10"),
    Shortcut("audio", "<Primary><Shift>F11", "Ctrl+Shift+F11"),
    Shortcut("pause", "<Primary><Shift>F12", "Ctrl+Shift+F12"),
)


def shortcut_names() -> Dict[str, str]:
    """The name each shortcut has in the GNOME keyboard settings (translated at install time)."""
    return {
        "video-audio": _("Record screen and sound"),
        "video": _("Record screen only"),
        "audio": _("Record sound only"),
        "pause": _("Pause or resume recording"),
    }


def path_of(shortcut: Shortcut) -> str:
    return "%s%s-%s/" % (PATH_PREFIX, APP_ID.rsplit(".", 1)[-1], shortcut.slug)


class ShortcutError(Exception):
    pass


Run = Callable[[Sequence[str]], Tuple[int, str]]


def _run(args: Sequence[str]) -> Tuple[int, str]:
    try:
        result = subprocess.run(
            list(args),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return 127, str(error)
    return result.returncode, result.stdout if result.returncode == 0 else result.stderr


def gvariant_string(value: str) -> str:
    """A GVariant text string: single quotes, ``\\`` and ``'`` escaped."""
    return "'%s'" % value.replace("\\", "\\\\").replace("'", "\\'")


def gvariant_list(values: Sequence[str]) -> str:
    return "[%s]" % ", ".join(gvariant_string(v) for v in values) if values else "@as []"


def parse_list(text: str) -> List[str]:
    """The paths of ``gsettings get`` (``@as []`` or ``['/a/', '/b/']``)."""
    text = text.strip()
    if text.startswith("@as"):
        text = text[3:].strip()
    try:
        value = ast.literal_eval(text)
    except (ValueError, SyntaxError) as error:
        raise ShortcutError("cannot read the keybinding list %r" % text) from error
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ShortcutError("cannot read the keybinding list %r" % text)
    return value


class Shortcuts:
    def __init__(self, command: str, run: Run = _run, which=shutil.which) -> None:
        """``command`` is what the key runs, up to the mode: ``hotrec`` or a path."""
        self.command = command
        self.run = run
        self.which = which

    def _need_gsettings(self) -> None:
        if not self.which("gsettings"):
            raise ShortcutError("gsettings not found: the keys are set in GNOME, with gsettings")

    def _get_list(self) -> List[str]:
        code, out = self.run(["gsettings", "get", SCHEMA, LIST_KEY])
        if code != 0:
            raise ShortcutError("gsettings get %s %s: %s" % (SCHEMA, LIST_KEY, out.strip()))
        return parse_list(out)

    def _set(self, args: Sequence[str]) -> None:
        code, out = self.run(["gsettings", *args])
        if code != 0:
            raise ShortcutError("gsettings %s: %s" % (" ".join(args), out.strip()))

    def _entry(self, path: str, key: str) -> str:
        code, out = self.run(["gsettings", "get", "%s:%s" % (ENTRY_SCHEMA, path), key])
        if code != 0:
            return ""
        try:
            value = ast.literal_eval(out.strip())
        except (ValueError, SyntaxError):
            return ""
        return value if isinstance(value, str) else ""

    def conflicts(self, existing: Sequence[str]) -> List[Tuple[Shortcut, str]]:
        """Our keys that another custom keybinding already uses: ``(ours, that entry's path)``."""
        ours = {path_of(s) for s in SHORTCUTS}
        found = []
        for path in existing:
            if path in ours:
                continue
            binding = self._entry(path, "binding")
            for shortcut in SHORTCUTS:
                if binding and binding.lower() == shortcut.accelerator.lower():
                    found.append((shortcut, path))
        return found

    def install(self) -> List[str]:
        """Add the four shortcuts. Returns the lines to show; raises ``ShortcutError`` when
        gsettings fails or when another custom keybinding already uses one of the keys (nothing
        is changed then)."""
        self._need_gsettings()
        existing = self._get_list()
        clash = self.conflicts(existing)
        if clash:
            raise ShortcutError(
                "already used by another custom keybinding: %s"
                % ", ".join("%s (%s)" % (s.keys, path) for s, path in clash)
            )
        names = shortcut_names()
        for shortcut in SHORTCUTS:
            target = "%s:%s" % (ENTRY_SCHEMA, path_of(shortcut))
            self._set(["set", target, "name", gvariant_string(names[shortcut.slug])])
            line = "%s %s" % (shlex.quote(self.command), shortcut.slug)
            self._set(["set", target, "command", gvariant_string(line)])
            self._set(["set", target, "binding", gvariant_string(shortcut.accelerator)])
        wanted = list(existing)
        for shortcut in SHORTCUTS:
            if path_of(shortcut) not in wanted:
                wanted.append(path_of(shortcut))
        if wanted != existing:
            self._set(["set", SCHEMA, LIST_KEY, gvariant_list(wanted)])
        return ["%s  %s %s" % (s.keys, shlex.quote(self.command), s.slug) for s in SHORTCUTS]

    def remove(self) -> List[str]:
        """Take the four shortcuts out. Returns the paths that were removed."""
        self._need_gsettings()
        existing = self._get_list()
        ours = {path_of(s) for s in SHORTCUTS}
        removed = [path for path in existing if path in ours]
        kept = [path for path in existing if path not in ours]
        if removed:
            self._set(["set", SCHEMA, LIST_KEY, gvariant_list(kept)])
        for shortcut in SHORTCUTS:
            if path_of(shortcut) in existing:
                target = "%s:%s" % (ENTRY_SCHEMA, path_of(shortcut))
                for key in ("name", "command", "binding"):
                    self._set(["reset", target, key])
        return removed

    def status(self) -> List[Tuple[Shortcut, Optional[str]]]:
        """Each shortcut and the command it runs now (``None``: not installed)."""
        self._need_gsettings()
        existing = self._get_list()
        return [
            (s, self._entry(path_of(s), "command") if path_of(s) in existing else None)
            for s in SHORTCUTS
        ]
