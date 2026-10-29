# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

"""A fake machine for the recorder: a /proc tree, processes that start and die on signals,
a clock that only moves when somebody sleeps. No test starts a real recorder."""

from __future__ import annotations

import os
import signal
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from hotrec import recorder as rec


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Dict[str, str]:
    """A home of its own. The process environment is cleaned of everything the language and the
    settings could be taken from, so a test never reads the developer's machine."""
    home = tmp_path / "home"
    runtime = tmp_path / "run"
    home.mkdir()
    runtime.mkdir(mode=0o700)
    values = {
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_RUNTIME_DIR": str(runtime),
        "XDG_DATA_HOME": str(home / ".local" / "share"),
        "XDG_DATA_DIRS": str(tmp_path / "usr-share"),  # no Shell extension of the developer's
    }
    for name in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "HOTREC_LOCALEDIR", "XDG_STATE_HOME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LANG", "C")
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return values


class FakeProcess:
    def __init__(self, world: "World", pid: int) -> None:
        self.world = world
        self.pid = pid

    def poll(self) -> Optional[int]:
        return None if self.pid in self.world.procs else 1


class World:
    """The processes of the fake machine, and every call the recorder made."""

    def __init__(self, tmp_path: Path) -> None:
        self.proc_root = tmp_path / "proc"
        self.proc_root.mkdir()
        self.procs: Dict[int, Dict[str, Any]] = {}
        self.next_pid = 4000
        self.next_start = 1000
        self.popen_calls: List[List[str]] = []
        self.kills: List[Any] = []
        self.notes: List[Any] = []
        self.slept = 0.0
        self.run_calls: List[List[str]] = []
        self.sink: Optional[str] = "alsa_output.test"
        self.fail_start = False  # the recorder exits at once
        self.missing: Optional[str] = None  # this program is not installed
        self.ignore_sigint = False  # the recorder does not stop on SIGINT
        self.ignore_sigterm = False
        self.write_on_int = True  # a clean stop leaves the file
        self.on_sleep = None
        self.log_text = ""  # what the recorder prints into its log (the fd it is handed)

    # -- /proc -----------------------------------------------------------------------------

    def add_process(self, comm: str, state: str = "S") -> int:
        pid = self.next_pid
        self.next_pid += 1
        self.next_start += 7
        self.procs[pid] = {"comm": comm, "state": state, "started": self.next_start, "out": None}
        self._write_proc(pid)
        return pid

    def _write_proc(self, pid: int) -> None:
        info = self.procs[pid]
        folder = self.proc_root / str(pid)
        folder.mkdir(exist_ok=True)
        fields = ["0"] * 18 + [str(info["started"])] + ["0"] * 5
        (folder / "stat").write_text(
            "%d (%s) %s %s" % (pid, info["comm"], info["state"], " ".join(fields))
        )

    def remove_process(self, pid: int) -> None:
        self.procs.pop(pid, None)
        stat = self.proc_root / str(pid) / "stat"
        if stat.exists():
            stat.unlink()

    # -- what the recorder is handed ---------------------------------------------------------

    def popen(self, command: List[str], **kwargs: Any) -> FakeProcess:
        self.popen_calls.append(list(command))
        program = command[0]
        if program == self.missing:
            raise FileNotFoundError(program)
        if program not in (rec.GSR, rec.FFMPEG):
            pid = self.add_process("python3")  # the indicator
            return FakeProcess(self, pid)
        comm = program[:15]
        pid = self.add_process(comm)
        self.procs[pid]["out"] = command[-1]
        if self.log_text:
            os.write(kwargs["stdout"], self.log_text.encode())
        if self.fail_start:
            self.remove_process(pid)
        return FakeProcess(self, pid)

    def kill(self, pid: int, number: int) -> None:
        self.kills.append((pid, number))
        if pid not in self.procs:
            raise ProcessLookupError(pid)
        info = self.procs[pid]
        if number == signal.SIGSTOP:
            info["state"] = "T"
            self._write_proc(pid)
        elif number == signal.SIGCONT:
            info["state"] = "S"
            self._write_proc(pid)
        elif number == signal.SIGINT and not self.ignore_sigint:
            if self.write_on_int and info["out"]:
                Path(info["out"]).write_bytes(b"data")
            self.remove_process(pid)
        elif number == signal.SIGTERM and not self.ignore_sigterm:
            self.remove_process(pid)
        elif number == signal.SIGKILL:
            self.remove_process(pid)

    def run(self, command: List[str], **kwargs: Any) -> subprocess.CompletedProcess:
        self.run_calls.append(list(command))
        if command[0] == "pactl":
            if self.sink is None:
                return subprocess.CompletedProcess(command, 1, "", "no pulse")
            return subprocess.CompletedProcess(command, 0, self.sink + "\n", "")
        raise AssertionError("unexpected run: %r" % (command,))

    def notify(self, summary: str, body: str = "") -> None:
        self.notes.append((summary, body))

    def sleep(self, seconds: float) -> None:
        self.slept += seconds
        if self.on_sleep:
            self.on_sleep()

    def now(self) -> datetime:
        return datetime(2026, 10, 29, 10, 30, 0)

    def recorder(self, env: Dict[str, str], **kwargs: Any) -> rec.Recorder:
        options: Dict[str, Any] = dict(
            env=env,
            popen=self.popen,
            kill=self.kill,
            run=self.run,
            notify=self.notify,
            sleep=self.sleep,
            now=self.now,
            proc_root=str(self.proc_root),
        )
        options.update(kwargs)
        return rec.Recorder(**options)

    def recorders(self) -> List[int]:
        return [pid for pid, i in self.procs.items() if i["comm"] in (rec.GSR[:15], rec.FFMPEG)]


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)
