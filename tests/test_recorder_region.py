# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

"""The area modes of the recorder: the choice of the area, the recording, the cut at the stop."""

import fcntl
import json
import subprocess
from pathlib import Path

import pytest

from hotrec import recorder as rec
from hotrec.region import Region

AREA = Region(0.25, 0.25, 0.75, 0.75, 1920 / 1080)
INFO = "  Stream #0:0: Video: h264 (High), yuv420p(tv), %dx%d [SAR 1:1 DAR 16:9], 30 fps\n"
BSF = "h264_metadata=crop_left=448:crop_right=480:crop_top=270:crop_bottom=278"


class Ffmpeg:
    """ffmpeg and the area window, as the recorder runs them (``world.run`` knows pactl)."""

    def __init__(self, world, size=(1920, 1080)):
        self.world = world
        self.size = size
        self.fail = False
        self.missing = False
        self.during_cut = None  # called when the cut starts, to look at the world meanwhile
        self.output = b"cropped video"
        self.calls = []
        self.selector_result = (0, AREA.to_json(), "")

    def __call__(self, command, **kwargs):
        if command[0] == rec.FFMPEG:
            self.calls.append(list(command))
            if self.missing:
                raise FileNotFoundError("ffmpeg")
            if "-c" not in command:  # the probe
                return subprocess.CompletedProcess(
                    command, 1, "", INFO % self.size if self.size else ""
                )
            if self.during_cut:
                self.during_cut()
            if self.fail:
                return subprocess.CompletedProcess(command, 1, "", "Invalid data found")
            Path(command[-1]).write_bytes(self.output)
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[1:] == ["-m", "hotrec", "select-region"]:
            code, out, err = self.selector_result
            return subprocess.CompletedProcess(command, code, out, err)
        return self.world.run(command, **kwargs)


@pytest.fixture
def ff(world):
    return Ffmpeg(world)


def region_recorder(world, env, ff, area=AREA, **kwargs):
    asked = []

    def choose():
        asked.append(1)
        return area

    recorder = world.recorder(env, run=ff, select_region=choose, **kwargs)
    recorder.asked = asked
    return recorder


def test_the_area_modes_are_modes_and_have_a_shortcut_each():
    from hotrec.shortcuts import SHORTCUTS

    assert rec.REGION_MODES == ("region-video-audio", "region-video")
    assert set(rec.REGION_MODES) <= set(rec.MODES)
    assert {s.slug for s in SHORTCUTS} == set(rec.MODES) | {"pause"}  # pause is no mode


@pytest.mark.parametrize("mode,sound", [("region-video-audio", True), ("region-video", False)])
def test_an_area_key_asks_for_the_area_then_records_the_whole_monitor(world, env, ff, mode, sound):
    recorder = region_recorder(world, env, ff)
    assert recorder.toggle(mode) == 0
    assert recorder.asked == [1]
    gsr = world.popen_calls[0]
    assert gsr == rec.video_command(rec.config.load(env)[0], sound, Path(gsr[-1]))
    assert ("-a" in gsr) is sound
    assert gsr[-1].endswith("_%s.mkv" % mode)
    state = recorder.read_state()
    assert state.mode == mode and state.region == AREA.as_list()
    saved = json.loads((Path(env["XDG_RUNTIME_DIR"]) / "hotrec" / "state.json").read_text())
    assert saved["region"] == AREA.as_list()
    assert world.notes == []


def test_a_cancelled_choice_starts_nothing_and_says_nothing(world, env, ff):
    recorder = region_recorder(world, env, ff, area=None)
    assert recorder.toggle("region-video") == 0
    assert world.popen_calls == [] and world.notes == []
    assert recorder.read_state() is None


def test_a_window_that_does_not_start_is_a_notification(world, env, ff):
    def broken():
        raise rec.RecorderError("The window to choose the area did not start")

    recorder = world.recorder(env, run=ff, select_region=broken)
    assert recorder.toggle("region-video") == 1
    assert world.notes == [
        ("Could not start the recording", "The window to choose the area did not start")
    ]
    assert world.popen_calls == []


def test_the_key_during_a_recording_stops_it_without_asking_for_an_area(world, env, ff):
    recorder = region_recorder(world, env, ff)
    recorder.toggle("region-video-audio")
    recorder.asked.clear()
    assert recorder.toggle("region-video-audio") == 0
    assert recorder.asked == []
    assert recorder.read_state() is None


def test_any_key_stops_an_area_recording_and_an_area_key_stops_any_recording(world, env, ff):
    recorder = region_recorder(world, env, ff)
    recorder.toggle("region-video")
    assert recorder.toggle(rec.VIDEO_AUDIO) == 0
    assert recorder.read_state() is None
    assert any("h264_metadata" in " ".join(c) for c in ff.calls)  # the area one was cut
    ff.calls.clear()
    recorder.toggle(rec.VIDEO)
    recorder.asked.clear()
    assert recorder.toggle("region-video") == 0
    assert recorder.asked == [] and recorder.read_state() is None
    assert not any("h264_metadata" in " ".join(c) for c in ff.calls)  # a whole-screen one: no cut


def test_a_second_key_press_while_the_area_window_is_open_opens_no_second_window(world, env, ff):
    opened = []
    inner = []

    def choose():
        opened.append(1)
        inner.append(recorder.toggle("region-video"))  # the key pressed again meanwhile
        return AREA

    recorder = world.recorder(env, run=ff, select_region=choose)
    assert recorder.toggle("region-video") == 0
    assert opened == [1] and inner == [0]
    assert len(world.recorders()) == 1


def test_a_recording_started_while_the_area_was_drawn_is_left_alone(world, env, ff):
    recorder = region_recorder(world, env, ff)
    other = world.recorder(env, run=ff)
    original = recorder.select_region

    def choose():
        other.toggle(rec.AUDIO)  # somebody else starts a recording meanwhile
        return original()

    recorder.select_region = choose
    assert recorder.toggle("region-video") == 0
    assert len(world.recorders()) == 1
    assert recorder.read_state().mode == rec.AUDIO


def test_the_area_window_runs_as_a_process_of_its_own_and_its_json_is_the_area(world, env, ff):
    recorder = world.recorder(env, run=ff)
    assert recorder._select_region() == AREA


def test_the_area_window_given_up_or_left_open_is_a_cancelled_choice(world, env, ff):
    recorder = world.recorder(env, run=ff)
    ff.selector_result = (rec.SELECT_CANCELLED, "", "")
    assert recorder._select_region() is None

    def hangs(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    assert world.recorder(env, run=hangs)._select_region() is None


@pytest.mark.parametrize(
    "result",
    [(1, "", "no display"), (0, "", ""), (0, "not json", ""), (0, '{"left": 2}', "")],
)
def test_an_area_window_that_fails_is_an_error_the_user_hears_about(world, env, ff, result):
    ff.selector_result = result
    with pytest.raises(rec.RecorderError):
        world.recorder(env, run=ff)._select_region()


def test_the_window_that_cannot_be_run_is_the_same_error(world, env):
    def broken(command, **kwargs):
        raise FileNotFoundError(command[0])

    with pytest.raises(rec.RecorderError):
        world.recorder(env, run=broken)._select_region()


# -- the cut at the stop ---------------------------------------------------------------------


def recorded(world, env, ff, mode="region-video-audio"):
    recorder = region_recorder(world, env, ff)
    recorder.toggle(mode)
    path = Path(recorder.read_state().file)
    return recorder, path


def test_the_stop_cuts_the_area_out_without_encoding_and_replaces_the_file(world, env, ff):
    recorder, path = recorded(world, env, ff)
    assert recorder.toggle("region-video-audio") == 0
    probe, cut = ff.calls
    assert probe == ["ffmpeg", "-hide_banner", "-i", str(path)]
    assert cut[cut.index("-c") + 1] == "copy"  # the streams are copied, nothing is encoded
    assert cut[cut.index("-bsf:v") + 1] == BSF
    assert cut[cut.index("-map") + 1] == "0"
    assert cut[cut.index("-i") + 1] == str(path)
    assert cut[-1] != str(path) and cut[-1].endswith(".mkv")  # written next to it first
    assert path.read_bytes() == b"cropped video"
    assert [p.name for p in path.parent.iterdir()] == [path.name]  # no temporary file left
    # a view cut, not a redaction: the notification says the rest of the screen is still in the file
    assert world.notes == [
        (
            "Recording saved",
            "%s\nOnly the view is cropped to the area: the rest of the screen stays in the file"
            % path,
        )
    ]


def test_a_video_of_another_size_with_the_same_shape_is_cut_by_the_fractions(world, env, ff):
    ff.size = (3840, 2160)
    recorder, path = recorded(world, env, ff)
    recorder.toggle("region-video")
    cut = ff.calls[1]
    assert cut[cut.index("-bsf:v") + 1] == (
        "h264_metadata=crop_left=960:crop_right=960:crop_top=540:crop_bottom=540"
    )


def test_ffmpeg_that_fails_leaves_the_whole_screen_and_says_so(world, env, ff):
    ff.fail = True
    recorder, path = recorded(world, env, ff)
    ff.output = b"x"
    assert recorder.toggle("region-video-audio") == 0
    assert path.read_bytes() == b"data"  # the recorder's own file, untouched
    assert [p.name for p in path.parent.iterdir()] == [path.name]
    assert world.notes == [
        ("Recording saved, but the area could not be cut out: the whole screen is in it", str(path))
    ]


def test_another_screen_than_the_one_drawn_on_is_not_cut(world, env, ff):
    ff.size = (1920, 1200)  # the portal recorded a 16:10 monitor
    recorder, path = recorded(world, env, ff)
    recorder.toggle("region-video")
    assert len(ff.calls) == 1  # only the probe
    assert path.read_bytes() == b"data"
    assert world.notes[0][0].startswith("Recording saved, but the area could not be cut out")


def test_a_video_whose_size_cannot_be_read_is_not_cut(world, env, ff):
    ff.size = None
    recorder, path = recorded(world, env, ff)
    recorder.toggle("region-video")
    assert len(ff.calls) == 1 and path.read_bytes() == b"data"
    assert world.notes[0][0].startswith("Recording saved, but")


def test_no_ffmpeg_is_the_same_whole_screen_message(world, env, ff):
    recorder, path = recorded(world, env, ff)
    ff.missing = True
    recorder.toggle("region-video")
    assert path.read_bytes() == b"data"
    assert world.notes[0][0].startswith("Recording saved, but")


def test_an_ffmpeg_that_hangs_leaves_no_half_written_copy(world, env, ff):
    recorder, path = recorded(world, env, ff)

    def hangs(command, **kwargs):
        if "-c" in command:
            Path(command[-1]).write_bytes(b"half")  # ffmpeg had started writing
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        return ff(command, **kwargs)

    recorder.run = hangs
    recorder.toggle("region-video")
    assert path.read_bytes() == b"data"
    assert [p.name for p in path.parent.iterdir()] == [path.name]
    assert world.notes[0][0].startswith("Recording saved, but")


def test_an_empty_result_is_not_put_in_place_of_the_recording(world, env, ff):
    ff.output = b""
    recorder, path = recorded(world, env, ff)
    recorder.toggle("region-video")
    assert path.read_bytes() == b"data"
    assert [p.name for p in path.parent.iterdir()] == [path.name]


def test_a_stop_that_leaves_no_file_is_not_cut_and_not_called_saved(world, env, ff):
    recorder, path = recorded(world, env, ff)
    world.write_on_int = False
    assert recorder.toggle("region-video") == 1
    assert ff.calls == []
    assert world.notes == [("The recording may be incomplete", str(path))]


def test_the_state_of_an_older_version_has_no_area_and_is_read(world, env, ff):
    recorder = region_recorder(world, env, ff)
    recorder.toggle(rec.VIDEO)
    state_file = Path(env["XDG_RUNTIME_DIR"]) / "hotrec" / "state.json"
    data = json.loads(state_file.read_text())
    del data["region"]  # what 0.1.4 wrote
    state_file.write_text(json.dumps(data))
    assert recorder.read_state().region is None
    data["region"] = "rubbish"
    state_file.write_text(json.dumps(data))
    assert recorder.read_state().region is None


def lock_is_free(recorder):
    with open(recorder.dir / "lock", "a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        return True


@pytest.mark.parametrize("key", ["region-video-audio", rec.VIDEO_AUDIO, "stop"])
def test_the_lock_is_free_while_the_area_is_cut_out(world, env, ff, key):
    # the cut can take minutes; a key pressed meanwhile (new recording, pause) must not wait for it
    recorder, _ = recorded(world, env, ff)
    seen = []
    ff.during_cut = lambda: seen.append((lock_is_free(recorder), recorder.read_state()))
    assert (recorder.stop() if key == "stop" else recorder.toggle(key)) == 0
    assert seen == [(True, None)]  # free, and the stopped recording is no longer "running"


def test_a_recording_started_while_the_area_is_cut_out_is_a_recording_of_its_own(world, env, ff):
    recorder, path = recorded(world, env, ff)
    started = []
    ff.during_cut = lambda: started.append(
        recorder.toggle(rec.VIDEO) if lock_is_free(recorder) else None
    )
    assert recorder.toggle("region-video-audio") == 0
    assert started == [0]
    assert path.read_bytes() == b"cropped video"
    state = recorder.read_state()
    assert state is not None and state.mode == rec.VIDEO and state.file != str(path)
