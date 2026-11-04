# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

"""Which video codecs the recorder says it can encode (what makes H.265 choosable)."""

import subprocess

from hotrec import codecs

SECTIONED = """section=system_info
display_server|wayland
section=gpu_info
vendor|intel
section=video_codecs
h264
hevc
av1
section=image_formats
jpeg
png
"""


class Answers:
    """Stands for ``subprocess.run``: one answer per question, in order (an exception is raised)."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.asked = []

    def __call__(self, command, **kwargs):
        self.asked.append(command)
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        code, out = answer
        return subprocess.CompletedProcess(command, code, out, "")


def test_the_codecs_section_of_the_info_output_is_read():
    run = Answers((0, SECTIONED))
    assert codecs.video_codecs(run) == {"h264", "h265"}
    assert run.asked == [["gpu-screen-recorder", "--info"]]


def test_only_the_video_codecs_section_counts():
    text = "section=gpu_info\nhevc\nsection=video_codecs\nh264\nsection=capture\nhevc\n"
    assert codecs.parse(text) == {"h264"}


def test_a_card_without_h265_gives_h264_only():
    run = Answers((0, "section=video_codecs\nh264\nsection=image_formats\njpeg\n"))
    assert codecs.video_codecs(run) == {"h264"}


def test_without_sections_a_line_that_is_just_a_codec_name_counts():
    assert codecs.parse("h264\nhevc\n") == {"h264", "h265"}
    assert codecs.parse("  HEVC \n") == {"h265"}


def test_words_that_only_contain_a_codec_name_do_not_count():
    assert codecs.parse("hevc is not supported\nno h264 here\n") == frozenset()
    assert codecs.parse("section=video_codecs\nhevc_hdr\nav1\nvp9\n") == frozenset()


def test_nothing_and_noise_name_no_codec():
    assert codecs.parse("") == frozenset()
    assert codecs.parse("\x00\x01 garbage\n") == frozenset()


def test_the_older_option_is_asked_when_info_names_nothing():
    run = Answers((0, "section=system_info\n"), (0, "h264\nhevc\n"))
    assert codecs.video_codecs(run) == {"h264", "h265"}
    assert run.asked[1] == ["gpu-screen-recorder", "--list-supported-video-codecs"]


def test_the_older_option_is_asked_when_info_is_not_an_option_yet():
    run = Answers((1, ""), (0, "h264\n"))
    assert codecs.video_codecs(run) == {"h264"}


def test_a_missing_program_means_no_codec_is_offered():
    run = Answers(FileNotFoundError("gpu-screen-recorder"), FileNotFoundError("again"))
    assert codecs.video_codecs(run) == frozenset()


def test_a_recorder_that_hangs_means_no_codec_is_offered():
    timeout = subprocess.TimeoutExpired("gpu-screen-recorder", codecs.PROBE_SECONDS)
    assert codecs.video_codecs(Answers(timeout, timeout)) == frozenset()


def test_a_recorder_that_fails_both_ways_means_no_codec_is_offered():
    assert codecs.video_codecs(Answers((1, "h264\nhevc\n"), (2, "hevc\n"))) == frozenset()


def test_the_question_is_asked_with_a_deadline_and_no_input():
    seen = {}

    def run(command, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(command, 0, SECTIONED, "")

    codecs.video_codecs(run)
    assert seen["timeout"] == codecs.PROBE_SECONDS and seen["stdin"] == subprocess.DEVNULL
    assert seen["capture_output"] is True and seen["check"] is False


def test_the_probe_of_the_window_asks_once_per_process(monkeypatch):
    from hotrec import settings_window

    asked = []
    monkeypatch.setattr(settings_window, "_PROBED", None)
    monkeypatch.setattr(
        settings_window.codecs, "video_codecs", lambda: asked.append(1) or frozenset({"h264"})
    )
    assert settings_window._probed_codecs() == {"h264"}
    assert settings_window._probed_codecs() == {"h264"}
    assert asked == [1]
