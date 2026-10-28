# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

"""The real command with real processes and real signals, against stand-ins for the programs it
drives (gpu-screen-recorder, ffmpeg, pactl, notify-send). What these cannot show: a real screen,
a real encoder, a real GNOME (see docs/measurements.md)."""

import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

FAKE_RECORDER = """#!/bin/bash
# stand-in for %(name)s: records its arguments, writes the file on SIGINT, notes SIGUSR2
out="${@: -1}"
echo "$@" > "$FAKE_DIR/%(name)s.args"
trap 'echo usr2 >> "$FAKE_DIR/%(name)s.events"' USR2
trap 'echo data > "$out"; echo int >> "$FAKE_DIR/%(name)s.events"; exit 0' INT
while true; do sleep 0.05; done
"""


@pytest.fixture
def machine(tmp_path, env, monkeypatch):
    fake = tmp_path / "fake"
    bin_dir = fake / "bin"
    bin_dir.mkdir(parents=True)
    for name in ("gpu-screen-recorder", "ffmpeg"):
        script = bin_dir / name
        script.write_text(FAKE_RECORDER % {"name": name})
        script.chmod(0o755)
    (bin_dir / "pactl").write_text("#!/bin/sh\necho fake_sink\n")
    (bin_dir / "notify-send").write_text('#!/bin/sh\necho "$@" >> "$FAKE_DIR/notify.log"\n')
    for name in ("pactl", "notify-send"):
        (bin_dir / name).chmod(0o755)
    base = dict(os.environ)
    base.update(env)
    base.update(
        PATH="%s:/usr/bin:/bin" % bin_dir,
        FAKE_DIR=str(fake),
        PYTHONPATH=str(REPO),
        LANG="C",
    )
    return fake, base


def hotrec(base, *args, timeout=60):
    return subprocess.run(
        [sys.executable, "-m", "hotrec", *args],
        env=base,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def events(fake, name):
    path = fake / (name + ".events")
    return path.read_text().split() if path.exists() else []


def wait_for(predicate, seconds=10):
    end = time.time() + seconds
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_screen_and_sound_start_pause_resume_stop(machine, env):
    fake, base = machine
    started = hotrec(base, "video-audio")
    assert started.returncode == 0, started.stderr
    status = hotrec(base, "status")
    assert status.returncode == 0 and status.stdout.startswith("video-audio ")
    path = Path(status.stdout.split()[1])
    assert path.parent == Path(env["HOME"]) / "Videos" / "Hotrec" and path.suffix == ".mkv"

    args = (fake / "gpu-screen-recorder.args").read_text().split()
    assert args[:5] == ["-w", "portal", "-restore-portal-session", "yes", "-f"]
    assert args[args.index("-encoder") + 1] == "gpu" and args[-1] == str(path)

    assert hotrec(base, "pause").returncode == 0
    assert wait_for(lambda: events(fake, "gpu-screen-recorder") == ["usr2"])
    assert hotrec(base, "status").stdout.endswith("(paused)\n")
    assert hotrec(base, "pause").returncode == 0
    assert wait_for(lambda: events(fake, "gpu-screen-recorder") == ["usr2", "usr2"])
    assert not hotrec(base, "status").stdout.endswith("(paused)\n")

    stopped = hotrec(base, "video")  # another key stops and saves
    assert stopped.returncode == 0, stopped.stderr
    assert path.read_text() == "data\n"
    assert events(fake, "gpu-screen-recorder")[-1] == "int"
    assert hotrec(base, "status").returncode == 1
    notes = (fake / "notify.log").read_text()
    assert "Recording saved" in notes and str(path) in notes


def test_sound_only_pause_is_a_real_stop_and_continue(machine, env):
    fake, base = machine
    assert hotrec(base, "audio").returncode == 0
    status = hotrec(base, "status").stdout.split()
    path = Path(status[1])
    assert path.suffix == ".mp3"
    args = (fake / "ffmpeg.args").read_text()
    assert "fake_sink.monitor" in args and "libmp3lame" in args and " -n " in " " + args + " "

    state_pid = int(
        __import__("json").loads(
            (Path(env["XDG_RUNTIME_DIR"]) / "hotrec" / "state.json").read_text()
        )["pid"]
    )

    def process_state():
        stat_text = Path("/proc/%d/stat" % state_pid).read_text()
        return stat_text[stat_text.rindex(")") + 2]

    hotrec(base, "pause")
    assert wait_for(lambda: process_state() == "T")
    hotrec(base, "pause")
    assert wait_for(lambda: process_state() in "SR")
    # stopping a paused recording works too
    hotrec(base, "pause")
    assert wait_for(lambda: process_state() == "T")
    stopped = hotrec(base, "audio")
    assert stopped.returncode == 0, stopped.stderr
    assert path.read_text() == "data\n"
    assert not Path("/proc/%d" % state_pid).exists()


def test_a_recorder_that_fails_at_once_tells_the_user(machine, env):
    fake, base = machine
    (fake / "bin" / "gpu-screen-recorder").write_text("#!/bin/sh\necho 'no gpu' >&2\nexit 3\n")
    result = hotrec(base, "video")
    assert result.returncode == 1
    notes = (fake / "notify.log").read_text()
    assert "Could not start the recording" in notes and "recorder.log" in notes
    log = Path(env["XDG_RUNTIME_DIR"]) / "hotrec" / "recorder.log"
    assert "no gpu" in log.read_text()
    assert hotrec(base, "status").returncode == 1


def test_a_missing_recorder_program_is_named(machine):
    fake, base = machine
    (fake / "bin" / "gpu-screen-recorder").unlink()
    result = hotrec(base, "video-audio")
    assert result.returncode == 1
    assert "gpu-screen-recorder is not installed" in (fake / "notify.log").read_text()


def test_the_first_start_writes_the_settings_file(machine, env):
    fake, base = machine
    hotrec(base, "video")
    conf = Path(env["XDG_CONFIG_HOME"]) / "hotrec.conf"
    assert conf.is_file()
    hotrec(base, "video")


def test_run_sh_runs_from_a_checkout_with_translated_notifications(machine, env, tmp_path):
    if shutil.which("msgfmt") is None:
        pytest.skip("msgfmt not installed")
    fake, base = machine
    gettext_dir = str(Path(shutil.which("msgfmt")).parent)
    base.update(
        LANG="hu_HU.UTF-8",
        XDG_CACHE_HOME=str(tmp_path / "cache"),
        PATH="%s:%s" % (base["PATH"], gettext_dir),
    )
    base.pop("PYTHONPATH")
    run = subprocess.run(
        [str(REPO / "run.sh"), "video"],
        env=base,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    stop = subprocess.run(
        [str(REPO / "run.sh"), "stop"],
        env=base,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert stop.returncode == 0, stop.stderr
    assert "A felvétel mentve" in (fake / "notify.log").read_text()
    caches = list((tmp_path / "cache" / "hotrec").glob("locale-*"))
    assert len(caches) == 1 and (caches[0] / "hu" / "LC_MESSAGES").is_dir()
    # a second run reuses the built catalogs
    before = caches[0].stat().st_mtime
    subprocess.run([str(REPO / "run.sh"), "status"], env=base, capture_output=True, check=False)
    assert len(list((tmp_path / "cache" / "hotrec").glob("*"))) == 1
    assert caches[0].stat().st_mtime == before


def test_the_script_is_executable_and_python_m_works(machine):
    fake, base = machine
    assert stat.S_IMODE((REPO / "run.sh").stat().st_mode) & 0o111
    result = hotrec(base, "--version")
    assert result.returncode == 0 and result.stdout.startswith("hotrec ")
