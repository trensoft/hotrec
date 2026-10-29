# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

"""The settings file, ``~/.config/hotrec.conf``.

A plain ``KEY=VALUE`` file with ``#`` comments. It is *read*, never sourced: nothing in it is run
by a shell, and a value that is wrong gets the default and a warning instead of stopping a
recording. The keys:

    FOLDER        where the recordings are saved (``$HOME``, ``${HOME}`` and a leading ``~`` expand)
    VIDEO_FOLDER  where video recordings are saved; not set (or empty): FOLDER
    AUDIO_FOLDER  where sound-only recordings are saved; not set (or empty): FOLDER
    CONTAINER     mkv (plays back even when the recording was cut short) or mp4
    VIDEO_KBPS    video bit rate, kbit/s
    FPS           frames per second
    AAC_KBPS      the sound of a video recording, kbit/s
    MP3_KBPS      a sound-only recording, kbit/s

There is no encoder key: video is always encoded by the graphics hardware (NVENC, VA-API).

The file is written on the first run. If the old ``felvetel.conf`` of the prototype exists then,
its values are imported once into the new file (and ``KODOLO``, the encoder choice, is dropped);
the old file is left alone.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Dict, List, Optional, Tuple

CONF_NAME = "hotrec.conf"
OLD_CONF_NAME = "felvetel.conf"

CONTAINERS = ("mkv", "mp4")

# key: (default, lowest, highest)
_NUMBERS: Dict[str, Tuple[int, int, int]] = {
    "VIDEO_KBPS": (12000, 500, 200000),
    "FPS": (30, 1, 240),
    "AAC_KBPS": (160, 32, 512),
    "MP3_KBPS": (192, 32, 320),
}
KEYS = ("FOLDER", "VIDEO_FOLDER", "AUDIO_FOLDER", "CONTAINER") + tuple(_NUMBERS)

# The prototype's names, and what they became. KODOLO, the choice of encoder, has no successor.
OLD_KEYS = {
    "MAPPA": "FOLDER",
    "KONTENER": "CONTAINER",
    "VIDEO_KBPS": "VIDEO_KBPS",
    "FPS": "FPS",
    "AAC_KBPS": "AAC_KBPS",
    "MP3_KBPS": "MP3_KBPS",
}

_LINE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")


@dataclass(frozen=True)
class Config:
    folder: str  # as written (with $HOME and so on); ``folder_path`` expands it
    container: str
    video_kbps: int
    fps: int
    aac_kbps: int
    mp3_kbps: int
    video_folder: str = ""  # "" = ``folder``
    audio_folder: str = ""

    def folder_path(self, env: Optional[Dict[str, str]] = None) -> Path:
        return Path(expand(self.folder, env))

    def folder_for(self, audio: bool) -> str:
        """The folder as written for a sound-only recording (``audio``) or a video one."""
        return (self.audio_folder if audio else self.video_folder) or self.folder


def config_home(env: Optional[Dict[str, str]] = None) -> Path:
    env = os.environ if env is None else env
    base = env.get("XDG_CONFIG_HOME")
    if base and os.path.isabs(base):
        return Path(base)
    return Path(env.get("HOME") or os.path.expanduser("~")) / ".config"


def config_path(env: Optional[Dict[str, str]] = None) -> Path:
    return config_home(env) / CONF_NAME


def old_config_path(env: Optional[Dict[str, str]] = None) -> Path:
    return config_home(env) / OLD_CONF_NAME


def expand(value: str, env: Optional[Dict[str, str]] = None) -> str:
    """``$HOME``, ``${HOME}`` and a leading ``~/`` only. No other variable, no command."""
    env = os.environ if env is None else env
    home = env.get("HOME") or os.path.expanduser("~")
    if value == "~" or value.startswith("~/"):
        value = home + value[1:]
    return re.sub(r"\$\{HOME\}|\$HOME(?![A-Za-z0-9_])", lambda _match: home, value)


def videos_dir(env: Optional[Dict[str, str]] = None) -> str:
    """The user's Videos folder: ``XDG_VIDEOS_DIR`` of ``user-dirs.dirs``, else ``$HOME/Videos``,
    written with ``$HOME`` in front so the file survives a moved home."""
    env = os.environ if env is None else env
    home = env.get("HOME") or os.path.expanduser("~")
    try:
        text = (config_home(env) / "user-dirs.dirs").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        text = ""
    for line in text.splitlines():
        match = re.match(r'^\s*XDG_VIDEOS_DIR\s*=\s*"([^"]*)"\s*$', line)
        if match:
            path = match.group(1)
            if path.startswith("$HOME/"):
                return path
            if path.startswith(home + "/"):
                return "$HOME/" + path[len(home) + 1 :]
    return "$HOME/Videos"


def default_config(env: Optional[Dict[str, str]] = None) -> Config:
    return Config(
        folder=videos_dir(env) + "/Hotrec",
        container="mkv",
        video_kbps=_NUMBERS["VIDEO_KBPS"][0],
        fps=_NUMBERS["FPS"][0],
        aac_kbps=_NUMBERS["AAC_KBPS"][0],
        mp3_kbps=_NUMBERS["MP3_KBPS"][0],
    )


def parse(text: str) -> Tuple[Dict[str, str], List[str]]:
    """The raw ``KEY: value`` pairs of a file, and the lines that could not be read. A value is
    either quoted (``"..."`` or ``'...'``, anything after the closing quote is a comment) or ends
    at the first ``#`` that follows a space. The last of two equal keys wins."""
    values: Dict[str, str] = {}
    problems: List[str] = []
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _LINE.match(line)
        if not match:
            problems.append("line %d is not KEY=VALUE" % number)
            continue
        key, rest = match.group(1), match.group(2).strip()
        if rest[:1] in ("'", '"'):
            end = rest.find(rest[0], 1)
            if end < 0:
                problems.append("line %d: the quote of %s is not closed" % (number, key))
                continue
            value = rest[1:end]
        else:
            value = re.split(r"\s+#", rest, maxsplit=1)[0].strip()
        values[key] = value
    return values, problems


def build(values: Dict[str, str], env: Optional[Dict[str, str]] = None) -> Tuple[Config, List[str]]:
    """A ``Config`` from raw values: unknown keys, bad numbers and a bad container are reported
    and replaced by the default."""
    warnings: List[str] = []
    config = default_config(env)
    for key in sorted(values):
        if key not in KEYS:
            warnings.append("%s is not a setting, ignored" % key)
    folder = values.get("FOLDER")
    if folder is not None:
        if not folder.strip():
            warnings.append("FOLDER is empty, using %s" % config.folder)
        elif '"' in folder and "'" in folder:
            warnings.append("FOLDER has both kinds of quote in it, using %s" % config.folder)
        else:
            config = replace(config, folder=folder.strip())
    for key in ("VIDEO_FOLDER", "AUDIO_FOLDER"):
        other = values.get(key)
        if other is None or not other.strip():  # not set, or empty: the same as FOLDER
            continue
        if '"' in other and "'" in other:
            warnings.append("%s has both kinds of quote in it, using FOLDER" % key)
        else:
            config = replace(config, **{key.lower(): other.strip()})
    container = values.get("CONTAINER")
    if container is not None:
        if container.lower() in CONTAINERS:
            config = replace(config, container=container.lower())
        else:
            warnings.append(
                "CONTAINER=%s is not one of %s, using %s"
                % (container, "/".join(CONTAINERS), config.container)
            )
    for key, (default, low, high) in _NUMBERS.items():
        if key not in values:
            continue
        text = values[key].strip()
        if text.isascii() and text.isdigit() and low <= int(text) <= high:
            config = replace(config, **{key.lower(): int(text)})
        else:
            warnings.append(
                "%s=%s is not a whole number from %d to %d, using %d"
                % (key, values[key], low, high, default)
            )
    return config, warnings


def render(config: Config, header: str = "") -> str:
    """The text of a settings file."""
    return (
        "%s# Hotrec settings. They apply from the next recording.\n"
        "FOLDER=%s      # where recordings are saved\n"
        "%s"
        "CONTAINER=%s                  # mkv (plays back even if cut short) or mp4\n"
        "VIDEO_KBPS=%d              # video bit rate, kbit/s\n"
        "FPS=%d\n"
        "AAC_KBPS=%d                # the sound of a video recording, kbit/s\n"
        "MP3_KBPS=%d                # a sound-only recording, kbit/s\n"
        % (
            header,
            _quote(config.folder),
            _folder_lines(config),
            config.container,
            config.video_kbps,
            config.fps,
            config.aac_kbps,
            config.mp3_kbps,
        )
    )


def _folder_lines(config: Config) -> str:
    """VIDEO_FOLDER and AUDIO_FOLDER: a line when set, else a comment that says they exist."""
    lines = ""
    for key, value in (
        ("VIDEO_FOLDER", config.video_folder),
        ("AUDIO_FOLDER", config.audio_folder),
    ):
        if value:
            lines += "%s=%s\n" % (key, _quote(value))
        else:
            lines += "# %s=    # not set: the FOLDER above\n" % key
    return lines


def portable(path: str, env: Optional[Dict[str, str]] = None) -> str:
    """A folder as it is written in the settings file: under the home folder it starts with
    ``$HOME``, so the file survives a moved home."""
    env = os.environ if env is None else env
    home = (env.get("HOME") or os.path.expanduser("~")).rstrip("/")
    if home and path.startswith(home + "/"):
        return "$HOME/" + path[len(home) + 1 :]
    return path


def set_values(updates: Dict[str, str], env: Optional[Dict[str, str]] = None) -> None:
    """Write ``KEY=value`` for each update into the settings file, keeping the rest of it
    (comments, other keys, their order). The last line of a key is the one that counts, so that
    one is replaced; a key that is not there yet is added at the end; an empty value removes the
    key's lines (the default applies again). Raises ``OSError`` when the file cannot be written and
    ``ValueError`` for a value that cannot be written (a line break, both kinds of quote)."""
    for key in updates:
        if key not in KEYS:
            raise ValueError("%s is not a setting" % key)
    for key, value in updates.items():
        if "\n" in value or "\r" in value or ('"' in value and "'" in value):
            raise ValueError("the value of %s cannot be written to the settings file" % key)
    path = config_path(env)
    if not path.exists():
        create(env)
    lines = path.read_text(encoding="utf-8").splitlines()
    for key, value in updates.items():
        found = [
            i for i, line in enumerate(lines) if (m := _LINE.match(line)) and m.group(1) == key
        ]
        if not value:
            for i in reversed(found):
                del lines[i]
        elif found:
            lines[found[-1]] = "%s=%s" % (key, _quote(value))
        else:
            lines.append("%s=%s" % (key, _quote(value)))
    _write(path, "\n".join(lines) + "\n")


def _quote(value: str) -> str:
    return "'%s'" % value if '"' in value else '"%s"' % value


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(".%s.%d.tmp" % (path.name, os.getpid()))
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def import_old(old: Path, env: Optional[Dict[str, str]] = None) -> Tuple[Config, List[str]]:
    """The values of the prototype's ``felvetel.conf`` as a ``Config``. The old file was a shell
    fragment; only the plain ``KEY=value`` lines it had are understood."""
    text = old.read_text(encoding="utf-8", errors="replace")
    old_values, problems = parse(text)
    values = {OLD_KEYS[key]: value for key, value in old_values.items() if key in OLD_KEYS}
    config, warnings = build(values, env)
    return config, [*problems, *warnings]


def load(env: Optional[Dict[str, str]] = None) -> Tuple[Config, List[str]]:
    """The settings, creating the file when there is none. Returns the config and the warnings
    (what to log). A file that cannot be read gives the defaults, never an exception."""
    path = config_path(env)
    if not path.exists():
        return create(env)
    try:
        values, problems = parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as error:
        return default_config(env), ["%s cannot be read (%s), using the defaults" % (path, error)]
    config, warnings = build(values, env)
    return config, [*problems, *warnings]


def create(env: Optional[Dict[str, str]] = None) -> Tuple[Config, List[str]]:
    """Write ``hotrec.conf``: from the old ``felvetel.conf`` when there is one, else defaults."""
    path = config_path(env)
    old = old_config_path(env)
    warnings: List[str] = []
    config, header = default_config(env), ""
    if old.is_file():
        try:
            config, warnings = import_old(old, env)
            header = "# Imported from %s (the encoder choice is gone: video is always\n" % old
            header += "# encoded by the graphics hardware).\n"
        except OSError as error:
            warnings.append("%s cannot be read (%s), using the defaults" % (old, error))
    try:
        _write(path, render(config, header))
    except OSError as error:
        warnings.append("%s cannot be written (%s)" % (path, error))
        return default_config(env), warnings
    return config, warnings
