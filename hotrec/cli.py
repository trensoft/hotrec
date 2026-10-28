# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

"""The ``hotrec`` command.

hotrec video-audio | video | audio   start this recording, or stop and save the one running
hotrec pause                         pause or resume
hotrec stop                          stop and save (does nothing when nothing records)
hotrec status                        one line; exit status 0 recording, 1 not
hotrec setup                         set the keyboard shortcuts and say so in a notification
hotrec shortcuts install|remove|status
hotrec indicator                     the top bar dot (started by a recording, not by hand)
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
from typing import List, Optional

from hotrec import _, __version__, i18n
from hotrec.recorder import AUDIO, MODES, VIDEO, VIDEO_AUDIO, Recorder
from hotrec.shortcuts import ShortcutError, Shortcuts

_LOG = logging.getLogger("hotrec")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hotrec",
        description="Screen and sound recorder for GNOME on Wayland, driven by keyboard shortcuts.",
    )
    parser.add_argument("--version", action="version", version="%(prog)s " + __version__)
    commands = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)
    for mode, text in (
        (VIDEO_AUDIO, "record the screen and the sound"),
        (VIDEO, "record the screen only"),
        (AUDIO, "record the sound only (MP3)"),
    ):
        commands.add_parser(mode, help="%s; or stop and save the running recording" % text)
    commands.add_parser("pause", help="pause or resume the running recording")
    commands.add_parser("stop", help="stop and save the running recording")
    commands.add_parser("status", help="print what is recording; exit status 0 if something is")
    commands.add_parser("setup", help="set the keyboard shortcuts and show a notification")
    commands.add_parser("indicator", help="the top bar dot (started by a recording)")
    shortcuts = commands.add_parser("shortcuts", help="manage the GNOME keyboard shortcuts")
    shortcuts.add_argument("action", choices=("install", "remove", "status"))
    shortcuts.add_argument(
        "--command",
        dest="run_command",
        metavar="PATH",
        help="what the keys run, up to the mode (default: hotrec, found on the PATH)",
    )
    return parser


def _shortcuts(command: Optional[str]) -> Shortcuts:
    command = command or shutil.which("hotrec")
    if not command:
        raise ShortcutError("hotrec is not on the PATH: give the command to run with --command")
    return Shortcuts(command)


def _do_shortcuts(action: str, command: Optional[str]) -> int:
    try:
        if action == "install":
            for line in _shortcuts(command).install():
                print(line)
        elif action == "remove":
            removed = _shortcuts(command or "hotrec").remove()
            print("removed %d shortcuts" % len(removed))
        else:
            for shortcut, run in _shortcuts(command or "hotrec").status():
                print("%-15s %s" % (shortcut.keys, run if run is not None else "not set"))
    except ShortcutError as error:
        print("hotrec: %s" % error, file=sys.stderr)
        return 1
    return 0


def _do_setup(recorder: Recorder) -> int:
    try:
        _shortcuts(None).install()
    except ShortcutError as error:
        _LOG.error("[setup] %s", error)
        recorder.notify(_("Could not set the keyboard shortcuts"), str(error))
        return 1
    recorder.notify(
        _("Keyboard shortcuts are set"),
        _(
            "Ctrl+Shift+F9: screen and sound. Ctrl+Shift+F10: screen only. "
            "Ctrl+Shift+F11: sound only. Ctrl+Shift+F12: pause or resume. "
            "Any of the first three stops and saves the recording."
        ),
    )
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    status = i18n.setup()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr)
    i18n.log_status(status)
    args = build_parser().parse_args(argv)
    recorder = Recorder()
    if args.command in MODES:
        return recorder.toggle(args.command)
    if args.command == "pause":
        return recorder.pause()
    if args.command == "stop":
        return recorder.stop()
    if args.command == "status":
        state = recorder.status()
        if state is None:
            print("not recording")
            return 1
        print("%s %s%s" % (state.mode, state.file, " (paused)" if state.paused else ""))
        return 0
    if args.command == "setup":
        return _do_setup(recorder)
    if args.command == "shortcuts":
        return _do_shortcuts(args.action, args.run_command)
    if args.command == "indicator":
        from hotrec import indicator

        return indicator.run(recorder)
    return 2  # argparse already refused anything else
