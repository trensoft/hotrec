# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

"""The six keyboard shortcuts, as GNOME custom keybindings.

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
from typing import Callable, Dict, FrozenSet, List, Mapping, Optional, Sequence, Tuple

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
    # new in 0.1.5; last, so the order of the first four (and what a person has set) is as it was
    Shortcut("region-video-audio", "<Primary><Shift>F7", "Ctrl+Shift+F7"),
    Shortcut("region-video", "<Primary><Shift>F8", "Ctrl+Shift+F8"),
)


# How the modifiers of an accelerator are spelled, by every name GTK and GNOME use for them.
_MODIFIER_NAMES = {
    "primary": "Primary",
    "control": "Primary",
    "ctrl": "Primary",
    "shift": "Shift",
    "alt": "Alt",
    "mod1": "Alt",
    "super": "Super",
    "mod4": "Super",
}
_MODIFIER_ORDER = ("Primary", "Shift", "Alt", "Super")
_LABEL_NAMES = {"Primary": "Ctrl", "Shift": "Shift", "Alt": "Alt", "Super": "Super"}
_ACCELERATOR = re.compile(r"((?:<[^<>\s]+>)*)([^<>\s]+)")
_FUNCTION_KEY = re.compile(r"F([1-9]|1[0-9]|2[0-4])", re.IGNORECASE)


def _parse_accelerator(text: str) -> Optional[Tuple[FrozenSet[str], str]]:
    """``(modifiers, key)`` of an accelerator in GTK notation, or ``None`` when it is not one
    (empty, ``disabled``, no key). The modifiers have one spelling (``Primary`` for Ctrl), so
    ``<Control><Shift>f9`` and ``<Primary><Shift>F9`` come out the same."""
    match = _ACCELERATOR.fullmatch(text.strip())
    if not match or match.group(2).lower() == "disabled":
        return None
    modifiers = set()
    for name in re.findall(r"<([^<>]+)>", match.group(1)):
        modifiers.add(_MODIFIER_NAMES.get(name.lower(), name))
    key = match.group(2)
    if len(key) == 1:
        key = key.lower()
    elif _FUNCTION_KEY.fullmatch(key):
        key = key.upper()
    return frozenset(modifiers), key


def canonical_accelerator(text: str) -> Optional[str]:
    """The accelerator in one spelling, ``<Primary><Shift>F9``; ``None`` when it is not one."""
    parsed = _parse_accelerator(text)
    if parsed is None:
        return None
    modifiers, key = parsed
    ordered = [m for m in _MODIFIER_ORDER if m in modifiers]
    ordered += sorted(modifiers - set(_MODIFIER_ORDER))
    return "".join("<%s>" % m for m in ordered) + key


def same_accelerator(left: str, right: str) -> bool:
    """Whether two accelerators are the same keys, however they are spelled."""
    a, b = _parse_accelerator(left), _parse_accelerator(right)
    return a is not None and b is not None and (a[0], a[1].lower()) == (b[0], b[1].lower())


def accelerator_label(text: str) -> str:
    """What a person reads: ``<Primary><Shift>F9`` is ``Ctrl+Shift+F9``. Text that is not an
    accelerator comes back as it is."""
    parsed = _parse_accelerator(text)
    if parsed is None:
        return text
    modifiers, key = parsed
    names = [_LABEL_NAMES[m] for m in _MODIFIER_ORDER if m in modifiers]
    names += sorted(modifiers - set(_MODIFIER_ORDER))
    return "+".join(names + [key[0].upper() + key[1:]])


def accelerator_problem(text: str) -> Optional[str]:
    """Why a key combination is no good as a recording shortcut, or ``None``. ``"keys"``: not a
    key combination at all; ``"modifier"``: a bare key (a letter would take it from every
    program), only the function keys may stand alone."""
    parsed = _parse_accelerator(text)
    if parsed is None:
        return "keys"
    modifiers, key = parsed
    if modifiers & {"Primary", "Alt", "Super"} or _FUNCTION_KEY.fullmatch(key):
        return None
    return "modifier"


def shortcut_names() -> Dict[str, str]:
    """The name each shortcut has in the GNOME keyboard settings (translated at install time)."""
    return {
        "region-video-audio": _("Record area and sound"),
        "region-video": _("Record area only"),
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
        self.skipped: List[Tuple[str, str]] = []  # (slug, path) ``add_missing`` left out: key taken

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
        self,
        existing: Sequence[str],
        ignore: Sequence[str] = (),
        wanted: Optional[Mapping[str, str]] = None,
    ) -> List[Tuple[Shortcut, str]]:
        """Our keys that another custom keybinding already uses: ``(ours, that entry's path)``.
        ``ignore`` are the entries about to be replaced; ``wanted`` is the accelerator of each
        slug (default: the default keys)."""
        ours = {path_of(s) for s in SHORTCUTS}
        found = []
        for path in existing:
            if path in ours or path in ignore:
                continue
            binding = self._entry(path, "binding")
            for shortcut in SHORTCUTS:
                keys = (wanted or {}).get(shortcut.slug, shortcut.accelerator)
                if binding and same_accelerator(binding, keys):
                    found.append((shortcut, path))
        return found

    def bindings(self) -> Dict[str, Optional[str]]:
        """The keys of each of our shortcuts now, as ``gsettings`` holds them (``None``: not
        installed, or no key in the entry)."""
        self._need_gsettings()
        existing = self._get_list()
        result: Dict[str, Optional[str]] = {}
        for s in SHORTCUTS:
            binding = self._entry(path_of(s), "binding") if path_of(s) in existing else ""
            result[s.slug] = binding or None
        return result

    def _wanted(self, keys: Optional[Mapping[str, str]]) -> Dict[str, str]:
        """The accelerator of each slug: the default, or the one in ``keys``. A key that is no
        accelerator, or one used by two of ours, is a ``ShortcutError``."""
        wanted = {s.slug: s.accelerator for s in SHORTCUTS}
        for slug, text in (keys or {}).items():
            if slug not in wanted:
                raise ShortcutError("no shortcut called %r" % slug)
            canonical = canonical_accelerator(text)
            if canonical is None:
                raise ShortcutError("%r is not a key combination" % text)
            wanted[slug] = canonical
        labels = [accelerator_label(text) for text in wanted.values()]
        if len(set(labels)) != len(labels):
            raise ShortcutError("two shortcuts have the same keys")
        return wanted

    def install(self, keys: Optional[Mapping[str, str]] = None) -> List[str]:
        """Add the six shortcuts and replace the prototype's keys (``self.replaced`` says which).
        ``keys`` maps a slug to the accelerator it should have (default: Ctrl+Shift+F7 to F12),
        so a shortcut that is already there gets the new keys. Returns the lines to show; raises
        ``ShortcutError`` when gsettings fails or the keys are no good, and ``ShortcutConflict``
        when another custom keybinding already uses one of the keys (nothing is changed then)."""
        wanted_keys = self._wanted(keys)
        self._need_gsettings()
        existing = self._get_list()
        old = self.legacy(existing)
        old_paths = [path for path, _command in old]
        clash = self.conflicts(existing, old_paths, wanted_keys)
        if clash:
            raise ShortcutConflict(
                "already used by another custom keybinding: %s"
                % ", ".join(
                    "%s (%s)" % (accelerator_label(wanted_keys[s.slug]), path) for s, path in clash
                )
            )
        names = shortcut_names()
        for shortcut in SHORTCUTS:
            target = "%s:%s" % (ENTRY_SCHEMA, path_of(shortcut))
            self._set(["set", target, "name", gvariant_string(names[shortcut.slug])])
            line = "%s %s" % (shlex.quote(self.command), shortcut.slug)
            self._set(["set", target, "command", gvariant_string(line)])
            self._set(["set", target, "binding", gvariant_string(wanted_keys[shortcut.slug])])
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
        return [
            "%s  %s %s"
            % (accelerator_label(wanted_keys[s.slug]), shlex.quote(self.command), s.slug)
            for s in SHORTCUTS
        ]

    def add_missing(self) -> List[str]:
        """Add the shortcuts of ours that are not in the list yet, with their default keys, and
        touch nothing else: the keys a person already set (or changed) stay as they are. This is
        how a version that brings new shortcuts reaches the people who installed the old ones.
        A default key that another custom keybinding (or one of our own entries) already has is
        not taken: that shortcut is left out and named in ``self.skipped``. Returns the slugs
        that were added."""
        self._need_gsettings()
        existing = self._get_list()
        missing = [s for s in SHORTCUTS if path_of(s) not in existing]
        self.skipped = []
        if not missing:
            return []
        used = [
            (self._entry(path, "binding"), path)
            for path in existing
            if path not in {path_of(s) for s in missing}
        ]
        added = []
        for shortcut in missing:
            clash = [
                path for binding, path in used if same_accelerator(binding, shortcut.accelerator)
            ]
            if clash:
                self.skipped.append((shortcut.slug, clash[0]))
                continue
            added.append(shortcut)
        names = shortcut_names()
        for shortcut in added:
            target = "%s:%s" % (ENTRY_SCHEMA, path_of(shortcut))
            self._set(["set", target, "name", gvariant_string(names[shortcut.slug])])
            line = "%s %s" % (shlex.quote(self.command), shortcut.slug)
            self._set(["set", target, "command", gvariant_string(line)])
            self._set(["set", target, "binding", gvariant_string(shortcut.accelerator)])
        if added:
            self._set(
                ["set", SCHEMA, LIST_KEY, gvariant_list(existing + [path_of(s) for s in added])]
            )
        return [s.slug for s in added]

    def remove(self) -> List[str]:
        """Take the six shortcuts out. Returns the paths that were removed."""
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
