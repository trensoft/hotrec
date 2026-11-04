# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

"""Which video codecs the graphics card can encode, as ``gpu-screen-recorder`` reports them.

The Settings window offers H.265 only when the card can encode it (NVENC on the PC, VA-API on the
Intel laptop). The recorder itself is asked, because it knows what its own encoder can open on
this machine; Hotrec does not guess from the name of the card. ``gpu-screen-recorder --info``
prints the codecs one per line (``h264``, ``hevc``, ...), after a ``section=video_codecs`` line
in the versions that group the output in sections; ``--list-supported-video-codecs`` is the older
way and prints only the codecs. Both are tried, and only a codec that is *named* counts: an
answer that is not understood, a program that is missing, one that fails or hangs is "this codec
is not offered". (The file ``hotrec.conf`` can still say ``VIDEO_CODEC=h265`` by hand.)

Not measured: the output of a real ``gpu-screen-recorder`` 6.x, which is not installed where
Hotrec is built and tested. The parsing follows the output as remembered from its source; the first
check on a real machine is what ``video_codecs()`` returns there.
"""

from __future__ import annotations

import logging
import subprocess
from typing import Callable, FrozenSet

_LOG = logging.getLogger(__name__)

GSR = "gpu-screen-recorder"
PROBE_SECONDS = 8
# What the recorder calls the codecs Hotrec can use; the name in the settings file is on the right.
KNOWN = {"h264": "h264", "hevc": "h265"}

# The ways to ask, the newer first.
_QUESTIONS = (("--info",), ("--list-supported-video-codecs",))
_SECTION = "section="
_CODEC_SECTION = "section=video_codecs"

Run = Callable[..., "subprocess.CompletedProcess[str]"]


def parse(output: str) -> FrozenSet[str]:
    """The codecs of Hotrec (``h264``, ``h265``) that the recorder's output names. With sections
    only the lines of the ``video_codecs`` section count; without any section line every line
    that is just a codec name does. Nothing else in the text matters."""
    lines = [line.strip().lower() for line in output.splitlines()]
    sectioned = any(line.startswith(_SECTION) for line in lines)
    found = set()
    inside = not sectioned
    for line in lines:
        if line.startswith(_SECTION):
            inside = line == _CODEC_SECTION
        elif inside and line in KNOWN:
            found.add(KNOWN[line])
    return frozenset(found)


def video_codecs(run: Run = subprocess.run) -> FrozenSet[str]:
    """The Hotrec codecs this machine's recorder can encode; empty when that cannot be told."""
    for question in _QUESTIONS:
        try:
            result = run(
                [GSR, *question],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=PROBE_SECONDS,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            _LOG.info("[codecs] %s %s did not answer: %s", GSR, " ".join(question), error)
            continue
        if result.returncode != 0:
            continue
        found = parse(result.stdout or "")
        if found:
            return found
    return frozenset()
