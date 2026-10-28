# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import os
import signal
import threading
from pathlib import Path

import pytest

from hotrec import config
from hotrec import recorder as rec

CFG = config.Config("/f", "mkv", 12000, 30, 160, 192)


# -- the commands ---------------------------------------------------------------------------


def test_video_with_sound_command():
    assert rec.video_command(CFG, True, Path("/f/x.mkv")) == [
        "gpu-screen-recorder",
        "-w",
        "portal",
        "-restore-portal-session",
        "yes",
        "-f",
        "30",
        "-k",
        "h264",
        "-encoder",
        "gpu",
        "-bm",
        "cbr",
        "-q",
        "12000",
        "-a",
        "default_output",
        "-ac",
        "aac",
        "-ab",
        "160",
        "-o",
        "/f/x.mkv",
    ]


def test_video_without_sound_has_no_audio_flags_and_no_cpu_encoder():
    command = rec.video_command(CFG, False, Path("/f/x.mkv"))
    assert "-a" not in command and "-ac" not in command and "-ab" not in command
    assert command[command.index("-encoder") + 1] == "gpu"
    assert "cpu" not in command and "libx264" not in command
    assert command[-2:] == ["-o", "/f/x.mkv"]


def test_the_settings_reach_the_command():
    cfg = config.Config("/f", "mp4", 8000, 60, 128, 320)
    command = rec.video_command(cfg, True, Path("/f/x.mp4"))
    assert command[command.index("-f") + 1] == "60"
    assert command[command.index("-q") + 1] == "8000"
    assert command[command.index("-ab") + 1] == "128"
    assert rec.audio_command(cfg, "m.monitor", Path("/f/x.mp3"))[-3:-1] == ["-b:a", "320k"]


def test_audio_command_never_overwrites_and_reads_the_monitor():
    command = rec.audio_command(CFG, "alsa_output.x.monitor", Path("/f/x.mp3"))
    assert command[0] == "ffmpeg" and "-n" in command and "-y" not in command
    assert command[command.index("-i") + 1] == "alsa_output.x.monitor"
    assert command[command.index("-c:a") + 1] == "libmp3lame"
    assert command[-1] == "/f/x.mp3"


def test_recording_path_names_and_never_collides(tmp_path, world):
    now = world.now()
    first = rec.recording_path(tmp_path, rec.VIDEO_AUDIO, CFG, now)
    assert first.name == "2026-10-29_103000_video-audio.mkv"
    first.write_bytes(b"")
    second = rec.recording_path(tmp_path, rec.VIDEO_AUDIO, CFG, now)
    assert second.name == "2026-10-29_103000_video-audio-2.mkv"
    assert rec.recording_path(tmp_path, rec.AUDIO, CFG, now).name == "2026-10-29_103000_audio.mp3"
    mp4 = config.Config("/f", "mp4", 1, 1, 1, 1)
    assert rec.recording_path(tmp_path, rec.VIDEO, mp4, now).name.endswith("_video.mp4")


# -- /proc ----------------------------------------------------------------------------------


def test_proc_identity_reads_comm_state_and_start(world):
    pid = world.add_process("gpu-screen-reco")
    info = rec.proc_identity(pid, str(world.proc_root))
    assert info == {"comm": "gpu-screen-reco", "state": "S", "started": world.procs[pid]["started"]}


def test_proc_identity_survives_a_comm_with_spaces_and_parens(world):
    pid = world.add_process("a (b) c")
    info = rec.proc_identity(pid, str(world.proc_root))
    assert info is not None and info["comm"] == "a (b) c" and info["state"] == "S"


def test_proc_identity_is_none_for_nothing_and_for_junk(world):
    assert rec.proc_identity(1, str(world.proc_root)) is None
    (world.proc_root / "9").mkdir()
    (world.proc_root / "9" / "stat").write_text("not a stat line")
    assert rec.proc_identity(9, str(world.proc_root)) is None
    (world.proc_root / "9" / "stat").write_text("9 (x) S 1 2 3")
    assert rec.proc_identity(9, str(world.proc_root)) is None


# -- the state directory ---------------------------------------------------------------------


def test_state_dir_is_private(env):
    path = rec.state_dir(env)
    assert path == Path(env["XDG_RUNTIME_DIR"]) / "hotrec"
    assert (path.stat().st_mode & 0o777) == 0o700


def test_state_dir_refuses_a_symlink(env, tmp_path):
    target = tmp_path / "elsewhere"
    target.mkdir()
    os.symlink(target, Path(env["XDG_RUNTIME_DIR"]) / "hotrec")
    with pytest.raises(rec.RecorderError):
        rec.state_dir(env)


def test_state_dir_without_a_runtime_dir_is_per_user_in_tmp(env):
    env = {k: v for k, v in env.items() if k != "XDG_RUNTIME_DIR"}
    path = rec.state_dir(env)
    try:
        assert path == Path("/tmp/hotrec-%d" % os.getuid())
        assert (path.stat().st_mode & 0o777) == 0o700
    finally:
        path.rmdir() if path.exists() and not any(path.iterdir()) else None


# -- start and stop -------------------------------------------------------------------------


def start(world, env, mode=rec.VIDEO_AUDIO, **kwargs):
    recorder = world.recorder(env, **kwargs)
    assert recorder.toggle(mode) == 0
    return recorder


def test_a_key_press_starts_a_recording(world, env):
    recorder = start(world, env)
    state = recorder.read_state()
    assert state is not None and state.mode == rec.VIDEO_AUDIO and not state.paused
    folder = Path(env["HOME"]) / "Videos" / "Hotrec"
    assert folder.is_dir()
    assert state.file == str(folder / "2026-10-29_103000_video-audio.mkv")
    gsr = world.popen_calls[0]
    assert gsr[0] == "gpu-screen-recorder" and gsr[-1] == state.file
    assert world.notes == []
    # the dot is started once, as the same python, in its own session
    assert world.popen_calls[1][1:] == ["-m", "hotrec", "indicator"]


def test_the_state_file_is_written_whole_and_private(world, env):
    start(world, env)
    path = Path(env["XDG_RUNTIME_DIR"]) / "hotrec" / "state.json"
    data = json.loads(path.read_text())
    assert set(data) == {"pid", "started", "mode", "file", "paused"}
    log = Path(env["XDG_RUNTIME_DIR"]) / "hotrec" / "recorder.log"
    assert (log.stat().st_mode & 0o777) == 0o600


def test_the_second_key_press_stops_and_saves_whatever_mode(world, env):
    recorder = start(world, env, rec.VIDEO_AUDIO)
    state = recorder.read_state()
    assert recorder.toggle(rec.AUDIO) == 0  # a different key still stops
    assert (state.pid, signal.SIGINT) in world.kills
    assert recorder.read_state() is None
    assert world.notes == [("Recording saved", state.file)]
    assert len(world.recorders()) == 0
    assert [c[0] for c in world.popen_calls].count("gpu-screen-recorder") == 1
    assert "ffmpeg" not in [c[0] for c in world.popen_calls]


def test_after_a_stop_the_next_key_starts_again(world, env):
    recorder = start(world, env)
    recorder.toggle(rec.VIDEO)
    recorder.toggle(rec.VIDEO)
    assert [c[0] for c in world.popen_calls].count("gpu-screen-recorder") == 2


def test_stop_command_does_nothing_when_idle(world, env):
    recorder = world.recorder(env)
    assert recorder.stop() == 0
    assert world.kills == [] and world.notes == []


def test_stop_command_stops(world, env):
    recorder = start(world, env, rec.VIDEO)
    assert recorder.stop() == 0
    assert world.notes[0][0] == "Recording saved"


def test_stopping_a_paused_recording_wakes_it_first(world, env):
    recorder = start(world, env, rec.AUDIO)
    recorder.pause()
    state = recorder.read_state()
    assert state.paused
    recorder.stop()
    sent = [n for pid, n in world.kills if pid == state.pid]
    assert sent == [signal.SIGSTOP, signal.SIGCONT, signal.SIGINT]


def test_a_recorder_that_ignores_sigint_gets_sigterm_and_the_user_is_told(world, env):
    world.ignore_sigint = True
    recorder = start(world, env, rec.VIDEO, stop_wait=0.5)
    state = recorder.read_state()
    assert recorder.toggle(rec.VIDEO) == 1
    sent = [n for pid, n in world.kills if pid == state.pid]
    assert sent == [signal.SIGINT, signal.SIGTERM]
    assert world.notes == [("The recording may be incomplete", state.file)]
    assert recorder.read_state() is None


def test_a_recorder_that_ignores_everything_is_killed(world, env):
    world.ignore_sigint = world.ignore_sigterm = True
    recorder = start(world, env, rec.VIDEO, stop_wait=0.2)
    state = recorder.read_state()
    recorder.toggle(rec.VIDEO)
    sent = [n for pid, n in world.kills if pid == state.pid]
    assert sent == [signal.SIGINT, signal.SIGTERM, signal.SIGKILL]


def test_a_stop_that_leaves_no_file_is_not_reported_as_saved(world, env):
    world.write_on_int = False
    recorder = start(world, env, rec.VIDEO)
    assert recorder.toggle(rec.VIDEO) == 1
    assert world.notes[0][0] == "The recording may be incomplete"


def test_a_recorder_that_is_already_gone_is_not_an_error_to_stop(world, env):
    recorder = start(world, env, rec.VIDEO)
    state = recorder.read_state()

    def vanish(pid, number):
        world.remove_process(pid)
        raise ProcessLookupError(pid)

    recorder.kill = vanish
    # the process disappears before the signal: read_state saw it alive, _send tolerates the race;
    # no file was written, so the user is told it may be incomplete
    assert recorder._stop(state) == 1
    assert world.notes == [("The recording may be incomplete", state.file)]
    assert recorder.read_state() is None


# -- starting can fail ------------------------------------------------------------------------


def test_a_recorder_that_exits_at_once_is_reported_with_the_log(world, env):
    world.fail_start = True
    recorder = world.recorder(env)
    assert recorder.toggle(rec.VIDEO_AUDIO) == 1
    assert recorder.read_state() is None
    summary, body = world.notes[0]
    assert summary == "Could not start the recording"
    assert body.endswith("recorder.log)") and "(log: " in body
    assert len(world.popen_calls) == 1  # no dot for a recording that never was


def test_a_missing_program_says_which(world, env):
    world.missing = "gpu-screen-recorder"
    recorder = world.recorder(env)
    assert recorder.toggle(rec.VIDEO) == 1
    assert world.notes == [
        ("Could not start the recording", "gpu-screen-recorder is not installed")
    ]


def test_audio_needs_a_sound_output(world, env):
    world.sink = None
    recorder = world.recorder(env)
    assert recorder.toggle(rec.AUDIO) == 1
    assert world.notes[0][1] == "Could not find the sound output to record"
    assert world.popen_calls == []


def test_audio_records_the_monitor_of_the_default_sink(world, env):
    recorder = start(world, env, rec.AUDIO)
    assert world.run_calls == [["pactl", "get-default-sink"]]
    command = world.popen_calls[0]
    assert command[0] == "ffmpeg" and "alsa_output.test.monitor" in command
    assert recorder.read_state().file.endswith("_audio.mp3")


def test_an_unusable_folder_is_reported(world, env, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    path = config.config_path(env)
    path.parent.mkdir(parents=True)
    path.write_text('FOLDER="%s/sub"\n' % blocker)
    recorder = world.recorder(env)
    assert recorder.toggle(rec.VIDEO) == 1
    assert world.notes[0][1].startswith("Could not create the folder")
    assert world.popen_calls == []


def test_the_folder_and_container_settings_are_used(world, env, tmp_path):
    path = config.config_path(env)
    path.parent.mkdir(parents=True)
    path.write_text('FOLDER="%s/out"\nCONTAINER=mp4\nFPS=60\n' % tmp_path)
    recorder = start(world, env, rec.VIDEO)
    state = recorder.read_state()
    assert state.file == str(tmp_path / "out" / "2026-10-29_103000_video.mp4")
    assert world.popen_calls[0][world.popen_calls[0].index("-f") + 1] == "60"


# -- stale state ------------------------------------------------------------------------------


def test_a_state_whose_process_is_gone_is_cleaned_and_a_key_starts(world, env):
    recorder = start(world, env, rec.VIDEO)
    state = recorder.read_state()
    world.remove_process(state.pid)  # the portal dialog was cancelled, the recorder left
    assert recorder.read_state() is None
    assert not (Path(env["XDG_RUNTIME_DIR"]) / "hotrec" / "state.json").exists()
    recorder.toggle(rec.VIDEO)
    assert recorder.read_state() is not None


def test_a_reused_pid_is_not_the_recorder(world, env):
    recorder = start(world, env, rec.VIDEO)
    state = recorder.read_state()
    world.remove_process(state.pid)
    # the kernel hands the same pid to an unrelated process
    world.procs[state.pid] = {
        "comm": "firefox",
        "state": "S",
        "started": state.started + 99,
        "out": None,
    }
    world._write_proc(state.pid)
    assert recorder.read_state() is None
    recorder.stop()
    assert (state.pid, signal.SIGINT) not in world.kills  # never signalled someone else's process


def test_a_zombie_is_not_a_running_recording(world, env):
    recorder = start(world, env, rec.VIDEO)
    state = recorder.read_state()
    world.procs[state.pid]["state"] = "Z"
    world._write_proc(state.pid)
    assert recorder.read_state() is None


def test_a_damaged_state_file_means_nothing_is_recording(world, env):
    recorder = world.recorder(env)
    (recorder.dir / "state.json").write_text("{not json")
    assert recorder.read_state() is None
    (recorder.dir / "state.json").write_text(json.dumps({"pid": "x"}))
    assert recorder.read_state() is None


# -- pause ------------------------------------------------------------------------------------


def test_pause_of_a_video_recording_is_sigusr2_and_toggles(world, env):
    recorder = start(world, env, rec.VIDEO_AUDIO)
    state = recorder.read_state()
    assert recorder.pause() == 0
    assert recorder.read_state().paused
    assert recorder.pause() == 0
    assert not recorder.read_state().paused
    assert [n for pid, n in world.kills if pid == state.pid] == [signal.SIGUSR2, signal.SIGUSR2]


def test_pause_of_a_sound_recording_is_stop_and_continue(world, env):
    recorder = start(world, env, rec.AUDIO)
    state = recorder.read_state()
    recorder.pause()
    recorder.pause()
    assert [n for pid, n in world.kills if pid == state.pid] == [signal.SIGSTOP, signal.SIGCONT]
    assert not recorder.read_state().paused


def test_pause_with_nothing_recording_does_nothing(world, env):
    recorder = world.recorder(env)
    assert recorder.pause() == 0
    assert world.kills == []


def test_status_is_the_state(world, env):
    recorder = world.recorder(env)
    assert recorder.status() is None
    start(world, env, rec.VIDEO)
    assert recorder.status().mode == rec.VIDEO


def test_an_unknown_mode_is_a_programming_error(world, env):
    with pytest.raises(ValueError):
        world.recorder(env).toggle("cpu")


# -- two key presses at once -------------------------------------------------------------------


def test_two_quick_key_presses_start_one_recording_not_two(world, env):
    inside = threading.Event()
    release = threading.Event()

    def slow_sleep():
        inside.set()
        release.wait(5)

    world.on_sleep = slow_sleep
    first = world.recorder(env)
    second = world.recorder(env)
    results = {}

    def press(name, recorder, mode):
        results[name] = recorder.toggle(mode)

    a = threading.Thread(target=press, args=("a", first, rec.VIDEO))
    a.start()
    assert inside.wait(5)  # a holds the lock, waiting for its recorder to prove itself
    b = threading.Thread(target=press, args=("b", second, rec.AUDIO))
    b.start()
    b.join(0.3)
    assert b.is_alive()  # b waits for the lock
    world.on_sleep = None
    release.set()
    a.join(5)
    b.join(5)
    assert results == {"a": 0, "b": 0}
    starts = [c[0] for c in world.popen_calls if c[0] in ("gpu-screen-recorder", "ffmpeg")]
    assert starts == ["gpu-screen-recorder"]  # b found a's recording and stopped it
    assert first.read_state() is None
    assert world.notes[0][0] == "Recording saved"
