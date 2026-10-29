# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

"""The four keyboard shortcuts, as GNOME custom keybindings.

GNOME on Wayland gives a program no global keys, so the keys are *the desktop's*: a custom
keybinding that runs ``hotrec <mode>``. They work in every window, which the keys of OBS do not
on Wayland. ``install`` adds ours to the list GNOME keeps in the GSettings key
``org.gnome.settings-daemon.plugins.media-keys custom-keybindings``, leaving the entries of other
programs alone; ``remove`` takes ours out again. Both are repeatable: running one twice changes
nothing the second time.

The shortcuts of the prototype this program grew out of (custom keybindings that run
``felvetel.sh kepeshang|kep|hang|szunet``) are *replaced*: ``install`` takes them out of the list
and resets their keys, because the new keys are the same four keys for the same job. An entry is
taken for a prototype one by its **command** only (``is_legacy_command``); its name and its dconf
path are not looked at, so another program's entry is never touched, whatever it is called.

``gsettings`` is the interface (a program that has no GSettings schema of its own writes through
it). It is run through ``run`` so the tests can answer for it.
"""

from __future__ import annotations

import ast
import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from hotrec import APP_ID, _

SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
LIST_KEY = "custom-keybindings"
ENTRY_SCHEMA = SCHEMA + ".custom-keybinding"
PATH_PREFIX = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/"

# What the prototype's keys ran: ``felvetel.sh <mode>`` (a script of any name before it: a path, a
# quote, ``bash``), or a ``felvetel-<mode>`` command of its own. The mode is a whole word.
_LEGACY_COMMAND = re.compile(
    r"""(?:^|[\s/'"])felvetel(?:\.sh)?['"]?\s+(?:kepeshang|kep|hang|szunet)(?![\w-])"""
    r"""|(?:^|[\s/'"])felvetel-(?:kepeshang|kep|hang|szunet)(?![\w-])"""
)


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


class ShortcutConflict(ShortcutError):
    """Another program's custom keybinding uses a key of ours: asking again changes nothing."""


def is_legacy_command(command: str) -> bool:
    """Whether a custom keybinding's command is one of the prototype's (see the module text)."""
    return bool(_LEGACY_COMMAND.search(command))


def done_marker(env: Optional[Mapping[str, str]] = None) -> Path:
    """The file that says the shortcuts were set at a login: ``$XDG_STATE_HOME/hotrec/...``, else
    ``~/.local/state/hotrec/...``. Removing it makes the next login do it again."""
    env = os.environ if env is None else env
    base = env.get("XDG_STATE_HOME")
    if base and os.path.isabs(base):
        root = Path(base)
    else:
        root = Path(env.get("HOME") or "~").expanduser() / ".local" / "state"
    return root / "hotrec" / "shortcuts-installed"


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
        self.replaced: List[str] = []  # commands of the prototype keys the last install replaced

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

    def legacy(self, existing: Sequence[str]) -> List[Tuple[str, str]]:
        """The prototype's keys in the list: ``(path, command)``."""
        ours = {path_of(s) for s in SHORTCUTS}
        found = []
        for path in existing:
            command = "" if path in ours else self._entry(path, "command")
            if command and is_legacy_command(command):
                found.append((path, command))
        return found

    def conflicts(
        self, existing: Sequence[str], ignore: Sequence[str] = ()
    ) -> List[Tuple[Shortcut, str]]:
        """Our keys that another custom keybinding already uses: ``(ours, that entry's path)``.
        ``ignore`` are the entries about to be replaced."""
        ours = {path_of(s) for s in SHORTCUTS}
        found = []
        for path in existing:
            if path in ours or path in ignore:
                continue
            binding = self._entry(path, "binding")
            for shortcut in SHORTCUTS:
                if binding and binding.lower() == shortcut.accelerator.lower():
                    found.append((shortcut, path))
        return found

    def install(self) -> List[str]:
        """Add the four shortcuts and replace the prototype's keys (``self.replaced`` says which).
        Returns the lines to show; raises ``ShortcutError`` when gsettings fails, and
        ``ShortcutConflict`` when another custom keybinding already uses one of the keys (nothing
        is changed then)."""
        self._need_gsettings()
        existing = self._get_list()
        old = self.legacy(existing)
        old_paths = [path for path, _command in old]
        clash = self.conflicts(existing, old_paths)
        if clash:
            raise ShortcutConflict(
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
        wanted = [path for path in existing if path not in old_paths]
        for shortcut in SHORTCUTS:
            if path_of(shortcut) not in wanted:
                wanted.append(path_of(shortcut))
        if wanted != existing:
            self._set(["set", SCHEMA, LIST_KEY, gvariant_list(wanted)])
        for path in old_paths:  # after the list: a failure above leaves the old keys as they were
            for key in ("name", "command", "binding"):
                self._set(["reset", "%s:%s" % (ENTRY_SCHEMA, path), key])
        self.replaced = [command for _path, command in old]
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
