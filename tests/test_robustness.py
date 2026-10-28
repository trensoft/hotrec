# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

"""Odd situations around the recording that a key press must survive."""

import json
import os
import signal
from pathlib import Path

from hotrec import recorder as rec


def test_a_state_file_left_by_a_crash_with_a_live_unrelated_process_is_ignored(world, env):
    recorder = world.recorder(env)
    pid = world.add_process("firefox")
    started = world.procs[pid]["started"] + 1  # the pid belongs to a different life now
    (recorder.dir / "state.json").write_text(
        json.dumps(dict(pid=pid, started=started, mode="video", file="/f/x.mkv", paused=False))
    )
    assert recorder.read_state() is None
    assert recorder.toggle(rec.VIDEO) == 0  # starts a new recording
    assert (pid, signal.SIGINT) not in world.kills


def test_pause_survives_a_process_that_just_left(world, env):
    recorder = world.recorder(env)
    recorder.toggle(rec.VIDEO)

    def gone(pid, number):
        raise ProcessLookupError(pid)

    recorder.kill = gone
    assert recorder.pause() == 1  # said so, did not raise
    assert recorder.read_state().paused is False


def test_the_log_file_is_never_followed_through_a_symlink(world, env, tmp_path):
    recorder = world.recorder(env)
    victim = tmp_path / "victim"
    victim.write_text("keep")
    os.symlink(victim, recorder.dir / "recorder.log")
    try:
        recorder.toggle(rec.VIDEO)
    except OSError:
        pass
    assert victim.read_text() == "keep"


def test_state_dir_is_created_with_the_runtime_dir_missing_parent(env, tmp_path):
    env = dict(env, XDG_RUNTIME_DIR=str(tmp_path / "newly" / "made"))
    path = rec.state_dir(env)
    assert path.is_dir() and (path.stat().st_mode & 0o777) == 0o700


def test_a_relative_runtime_dir_is_not_used(env):
    env = dict(env, XDG_RUNTIME_DIR="relative/dir")
    path = rec.state_dir(env)
    try:
        assert path == Path("/tmp/hotrec-%d" % os.getuid())
    finally:
        if not any(path.iterdir()):
            path.rmdir()
