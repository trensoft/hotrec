# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

"""The area of the screen to record: what is chosen, and how it is cut out of the video.

The recorder always records a whole monitor through the desktop portal. The area is cut out when
the recording stops, **without encoding the video again**: ``ffmpeg -c copy -bsf:v
h264_metadata=crop_*`` rewrites the cropping values in the H.264 headers (SPS) of the stream. The
picture data is not touched, so it takes seconds and needs no video encoder (the Fedora ffmpeg
has no software H.264 encoder). Measured with ffmpeg 7.0: the picture a player shows is bit for
bit the one the
``crop`` filter gives.

This crops the **view**; it is not a redaction. The picture data of the whole monitor stays in the
file, the cropping can be removed again with one ffmpeg command, and some players ignore it. The
README, the man page and the notification after the recording say so; do not call it "cut out"
in text a person reads without saying what stays.

Two limits of the headers, both handled here:

- the cropping values are counted against the *coded* size, which is the visible size rounded up
  to 16 (1080 lines are coded as 1088), and they come in steps of 2 pixels;
- ffmpeg based players cut the **left** edge exactly only at a multiple of 64 pixels, so the left
  edge is moved to the left to such a column (at most 63 pixels more on that side).

The area is kept as fractions of the monitor it was chosen on (``Region``), so it does not matter
how many pixels the portal stream has (scaling, fractional scaling): the fractions are applied to
the size of the recorded video.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import List, Optional, Tuple

MIN_PIXELS = 16  # what is left of the picture must be at least this wide and high
LEFT_STEP = 64
ASPECT_TOLERANCE = 0.02  # the recorded screen must have the shape of the one that was drawn on


@dataclass(frozen=True)
class Region:
    """The chosen area: the edges as fractions (0..1) of the monitor, and the monitor's width
    divided by its height (to notice that the portal recorded another screen)."""

    left: float
    top: float
    right: float
    bottom: float
    aspect: float

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, text: str) -> "Region":
        data = json.loads(text)
        region = cls(*(float(data[key]) for key in ("left", "top", "right", "bottom", "aspect")))
        if not region.valid():
            raise ValueError("not an area: %r" % text)
        return region

    @classmethod
    def from_list(cls, values: object) -> Optional["Region"]:
        """The area as the state file keeps it (``[left, top, right, bottom, aspect]``), or
        ``None`` for anything else."""
        try:
            region = cls(*(float(v) for v in values))  # type: ignore[attr-defined]
        except (TypeError, ValueError):
            return None
        return region if region.valid() else None

    def as_list(self) -> List[float]:
        return [self.left, self.top, self.right, self.bottom, self.aspect]

    def valid(self) -> bool:
        return (
            0.0 <= self.left < self.right <= 1.0
            and 0.0 <= self.top < self.bottom <= 1.0
            and self.aspect > 0
        )


@dataclass(frozen=True)
class Crop:
    """The four values of ``h264_metadata`` (pixels, against the coded size)."""

    left: int
    right: int
    top: int
    bottom: int

    def bitstream_filter(self) -> str:
        return "h264_metadata=crop_left=%d:crop_right=%d:crop_top=%d:crop_bottom=%d" % (
            self.left,
            self.right,
            self.top,
            self.bottom,
        )


def region_from_drag(
    x0: float, y0: float, x1: float, y1: float, width: float, height: float, minimum: float = 24
) -> Optional[Region]:
    """The area of a mouse drag inside a window of ``width`` x ``height``, from the press point
    to the release point (either corner first). ``None`` when it is smaller than ``minimum`` in
    either direction (a click, not a drag) or the window has no size."""
    if width <= 0 or height <= 0:
        return None
    left, right = sorted((min(max(x0, 0.0), width), min(max(x1, 0.0), width)))
    top, bottom = sorted((min(max(y0, 0.0), height), min(max(y1, 0.0), height)))
    if right - left < minimum or bottom - top < minimum:
        return None
    return Region(left / width, top / height, right / width, bottom / height, width / height)


def _ceil16(value: int) -> int:
    return (value + 15) // 16 * 16


def crop_for(region: Region, width: int, height: int) -> Optional[Crop]:
    """The cropping values for a video of ``width`` x ``height`` visible pixels. ``None`` when
    the video does not have the shape of the monitor the area was drawn on, or what is left is
    too small to be a picture."""
    if width <= 0 or height <= 0:
        return None
    if abs((width / height) / region.aspect - 1.0) > ASPECT_TOLERANCE:
        return None
    left = int(region.left * width) // LEFT_STEP * LEFT_STEP
    right = min(width, int(round(region.right * width / 2.0)) * 2)
    top = int(region.top * height) // 2 * 2
    bottom = min(height, int(round(region.bottom * height / 2.0)) * 2)
    if right - left < MIN_PIXELS or bottom - top < MIN_PIXELS:
        return None
    return Crop(left, _ceil16(width) - right, top, _ceil16(height) - bottom)


_SIZE = re.compile(r"Video:.*?, (\d{2,5})x(\d{2,5})(?=[ ,\[])")


def video_size(ffmpeg_info: str) -> Optional[Tuple[int, int]]:
    """``(width, height)`` of the first video stream in what ``ffmpeg -i FILE`` prints."""
    match = _SIZE.search(ffmpeg_info)
    return (int(match.group(1)), int(match.group(2))) if match else None
