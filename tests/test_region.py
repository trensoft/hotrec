# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

"""The area of the screen: the drag, the cropping values, the size of a video."""

import json

import pytest

from hotrec import region as rg
from hotrec import selector


def test_a_drag_in_any_direction_is_the_same_area():
    expected = rg.Region(0.25, 0.5, 0.75, 0.75, 2.0)
    assert rg.region_from_drag(250, 500, 750, 750, 1000, 1000) is not None
    a = rg.region_from_drag(500, 100, 1500, 400, 2000, 1000)
    b = rg.region_from_drag(1500, 400, 500, 100, 2000, 1000)
    assert a == b == rg.Region(0.25, 0.1, 0.75, 0.4, 2.0)
    assert rg.region_from_drag(500, 500, 1500, 750, 2000, 1000) == expected


def test_a_drag_outside_the_window_is_kept_inside_it():
    area = rg.region_from_drag(-50, -50, 5000, 900, 1000, 800)
    assert area == rg.Region(0.0, 0.0, 1.0, 1.0, 1.25)


@pytest.mark.parametrize(
    "drag",
    [
        (10, 10, 10, 10),  # a click
        (10, 10, 100, 20),  # a line
        (10, 10, 20, 100),
        (0, 0, 23, 500),  # under the 24 pixels of the default
    ],
)
def test_a_click_or_a_sliver_is_no_area(drag):
    assert rg.region_from_drag(*drag, 1000, 1000) is None


def test_a_window_without_size_gives_no_area():
    assert rg.region_from_drag(0, 0, 100, 100, 0, 100) is None
    assert rg.region_from_drag(0, 0, 100, 100, 100, 0) is None


def test_the_area_goes_through_json_and_the_state_list():
    area = rg.Region(0.1, 0.2, 0.6, 0.9, 16 / 9)
    assert rg.Region.from_json(area.to_json()) == area
    assert rg.Region.from_list(area.as_list()) == area


@pytest.mark.parametrize(
    "values",
    [
        None,
        "x",
        [],
        [0, 0, 1, 1],  # no aspect
        [0.5, 0, 0.5, 1, 1.0],  # no width
        [0, 0.9, 1, 0.2, 1.0],  # upside down
        [-0.1, 0, 1, 1, 1.0],
        [0, 0, 1.2, 1, 1.0],
        [0, 0, 1, 1, 0],  # no shape
        ["a", 0, 1, 1, 1.0],
    ],
)
def test_nothing_else_is_an_area(values):
    assert rg.Region.from_list(values) is None


def test_json_that_is_not_an_area_is_refused():
    for text in (
        "",
        "[]",
        '{"left": 0}',
        json.dumps({"left": 0.5, "top": 0, "right": 0.1, "bottom": 1, "aspect": 1}),
    ):
        with pytest.raises((ValueError, KeyError, TypeError)):
            rg.Region.from_json(text)


# -- the cropping values ---------------------------------------------------------------------


def test_the_crop_of_a_full_hd_video():
    area = rg.Region(0.25, 0.25, 0.75, 0.75, 1920 / 1080)
    crop = rg.crop_for(area, 1920, 1080)
    # left 480 -> 448 (a multiple of 64); right edge 1440; top 270; bottom edge 810
    # coded size 1920 x 1088: right 1920 - 1440 = 480, bottom 1088 - 810 = 278
    assert crop == rg.Crop(left=448, right=480, top=270, bottom=278)
    assert crop.bitstream_filter() == (
        "h264_metadata=crop_left=448:crop_right=480:crop_top=270:crop_bottom=278"
    )


def test_the_left_edge_is_a_multiple_of_64_and_never_to_the_right_of_the_drawn_one():
    for left in (0.0, 0.01, 0.0333, 0.1, 0.333, 0.5, 0.9):
        area = rg.Region(left, 0.1, min(left + 0.08, 1.0), 0.6, 16 / 9)
        crop = rg.crop_for(area, 1920, 1080)
        assert crop is not None
        assert crop.left % 64 == 0
        assert 0 <= left * 1920 - crop.left < 64


def test_the_other_edges_are_even_and_the_whole_screen_is_no_crop_at_all():
    area = rg.Region(0.0, 0.0, 1.0, 1.0, 16 / 9)
    assert rg.crop_for(area, 1920, 1080) == rg.Crop(0, 0, 0, 8)  # 1080 is coded as 1088
    odd = rg.Region(0.1, 0.1234, 0.8765, 0.9, 16 / 9)
    crop = rg.crop_for(odd, 1920, 1080)
    assert crop is not None and crop.top % 2 == 0 and crop.bottom % 2 == 0 and crop.right % 2 == 0


def test_a_width_that_is_not_a_multiple_of_16_is_counted_against_the_coded_width():
    area = rg.Region(0.0, 0.0, 0.5, 0.5, 1366 / 768)
    crop = rg.crop_for(area, 1366, 768)
    assert crop == rg.Crop(0, 1376 - 683 - 1, 0, 768 - 384)  # right edge 682 (even)


def test_the_shape_of_the_video_must_be_the_shape_of_the_screen_it_was_drawn_on():
    area = rg.Region(0.1, 0.1, 0.9, 0.9, 16 / 9)
    assert rg.crop_for(area, 1920, 1080) is not None
    assert rg.crop_for(area, 3840, 2160) is not None  # the same shape, another size
    assert rg.crop_for(area, 1920, 1200) is None  # another monitor (16:10)
    assert rg.crop_for(area, 1080, 1920) is None


def test_what_is_left_must_be_a_picture():
    sliver = rg.Region(0.5, 0.5, 0.5 + 8 / 1920, 0.9, 16 / 9)
    assert rg.crop_for(sliver, 1920, 1080) is None
    assert rg.crop_for(rg.Region(0, 0, 1, 1, 1.0), 0, 100) is None


VIDEO_INFO = """Input #0, matroska,webm, from 'x.mkv':
  Duration: 00:00:05.00, start: 0.000000, bitrate: 12000 kb/s
  Stream #0:0: Video: h264 (High), yuv420p(tv), 1920x1080 [SAR 1:1 DAR 16:9], 30 fps
  Stream #0:1: Audio: aac (LC), 48000 Hz, stereo, fltp
At least one output file must be specified
"""


def test_the_size_is_read_from_the_first_video_stream():
    assert rg.video_size(VIDEO_INFO) == (1920, 1080)
    mp4 = (
        "Stream #0:0[0x1](und): Video: h264 (High) (avc1 / 0x31637661), "
        "yuv420p(progressive), 2560x1440, 11999 kb/s, 30 fps"
    )
    assert rg.video_size(mp4) == (2560, 1440)
    assert rg.video_size("Stream #0:0: Audio: mp3, 44100 Hz") is None
    assert rg.video_size("") is None


# -- the drag in a window --------------------------------------------------------------------


def test_a_drag_selection_follows_the_mouse_and_answers_on_release():
    drag = selector.DragSelection(1000, 500)
    assert drag.rectangle() is None
    drag.motion(5, 5)  # no button: nothing
    assert drag.rectangle() is None
    drag.press(300, 100)
    drag.motion(200, 250)
    assert drag.rectangle() == (200, 100, 100, 150)
    area = drag.release(100, 300)
    assert area == rg.Region(0.1, 0.2, 0.3, 0.6, 2.0)
    assert drag.rectangle() is None


def test_a_click_gives_nothing_and_the_user_can_draw_again():
    drag = selector.DragSelection(1000, 500)
    drag.press(10, 10)
    assert drag.release(12, 11) is None
    assert drag.rectangle() is None
    drag.press(100, 100)
    assert drag.release(400, 300) is not None


def test_a_release_without_a_press_is_nothing():
    assert selector.DragSelection(100, 100).release(50, 50) is None


def test_the_painted_rectangle_stays_inside_the_window():
    drag = selector.DragSelection(100, 100)
    drag.press(50, 50)
    drag.motion(500, -20)
    assert drag.rectangle() == (50, 0, 50, 50)


def test_without_gtk_3_the_window_says_so_and_fails(monkeypatch, capsys):
    def missing():
        raise ImportError("no GTK")

    monkeypatch.setattr(selector, "_load_toolkit", missing)
    assert selector.run() == 1
    assert "needs GTK 3" in capsys.readouterr().err
