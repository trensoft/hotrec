# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

"""Start, pause and stop a recording. One recording at a time; every key press is one command.

The three modes share one rule (the prototype's): a key starts its recording when nothing is
recording and, when something is, stops and saves it, whichever mode that one is.

- ``video-audio`` and ``video``: ``gpu-screen-recorder`` in portal mode (the desktop asks which
  screen, and remembers the answer). Pause is SIGUSR2 (the recorder toggles), stop is SIGINT.
- ``audio``: ``ffmpeg`` records the monitor of the default sound output as MP3. Pause is SIGSTOP
  and SIGCONT, stop is SIGINT.

What is running is kept in ``$XDG_RUNTIME_DIR/hotrec/state.json`` (pid, the start time of that
pid so a reused pid is not mistaken for the recorder, mode, file, paused). The commands take a
lock on ``lock`` in the same directory, so two quick key presses cannot both start a recording.

Everything that touches the system (starting a process, signals, ``/proc``, the clock, sleeping,
notifications) is a parameter of ``Recorder``, so the tests run the whole logic without a screen.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import signal
import stat
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional

from hotrec import APP_NAME, _, config

_LOG = logging.getLogger(__name__)

VIDEO_AUDIO = "video-audio"
VIDEO = "video"
AUDIO = "audio"
MODES = (VIDEO_AUDIO, VIDEO, AUDIO)

GSR = "gpu-screen-recorder"
FFMPEG = "ffmpeg"
# The kernel keeps 15 characters of a process name.
_COMM = {GSR: GSR[:15], FFMPEG: FFMPEG}

START_CHECK_SECONDS = 1.5  # a recorder that is gone this soon did not start
STOP_WAIT_SECONDS = 20.0  # SIGINT: the recorder writes the end of the file
KILL_WAIT_SECONDS = 5.0
_TICK = 0.1


# What the recorder prints when the graphics hardware cannot encode video. ``vaInitialize failed``
# is the VA-API driver missing (an Intel laptop without intel-media-driver); the rest is any other
# word of an encoder failure.
_VAAPI_WORDS = ("vainitialize", "libva", "va-api", "vaapi")
_ENCODER_WORDS = ("nvenc", "cuda", "encoder", "encoding")
_LOG_TAIL_BYTES = 8192


def encoder_problem(log_text: str) -> Optional[str]:
    """What to tell the user when the video recorder's log (its last lines) shows that the
    encoder did not start: what is missing, in the user's language. ``None`` when the log does
    not look like an encoder failure (a cancelled screen choice, say)."""
    text = log_text.lower()
    if any(word in text for word in _VAAPI_WORDS):
        return _(
            "The VA-API video driver is missing or does not work. "
            "On Intel graphics, install intel-media-driver (RPM Fusion nonfree), then try again."
        )
    if any(word in text for word in _ENCODER_WORDS):
        return _(
            "The video encoder did not start. "
            "The graphics driver may lack hardware video encoding (VA-API or NVENC)."
        )
    return None


class RecorderError(Exception):
    """A failure the user should hear about; the message is already translated."""


@dataclass
class State:
    pid: int
    started: int  # the start time of the pid, from /proc (clock ticks since boot)
    mode: str
    file: str
    paused: bool = False


def state_dir(env: Optional[Dict[str, str]] = None) -> Path:
    """``$XDG_RUNTIME_DIR/hotrec``, else ``/tmp/hotrec-<uid>``; either is made 0700 and must be
    ours (a shared ``/tmp`` is where someone else could plant the directory)."""
    env = os.environ if env is None else env
    base = env.get("XDG_RUNTIME_DIR")
    path = (
        Path(base) / "hotrec"
        if base and os.path.isabs(base)
        else Path("/tmp/hotrec-%d" % os.getuid())
    )
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = os.lstat(path)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise RecorderError(_("%s is not a safe place for the state of the recording") % path)
    os.chmod(path, 0o700)
    return path


def video_command(cfg: config.Config, with_sound: bool, out: Path) -> List[str]:
    """``gpu-screen-recorder`` through the desktop portal; H.264 from the graphics hardware."""
    command = [
        GSR,
        "-w",
        "portal",
        "-restore-portal-session",
        "yes",
        "-f",
        str(cfg.fps),
        "-k",
        "h264",
        "-encoder",
        "gpu",
        "-bm",
        "cbr",
        "-q",
        str(cfg.video_kbps),
    ]
    if with_sound:
        command += ["-a", "default_output", "-ac", "aac", "-ab", str(cfg.aac_kbps)]
    return command + ["-o", str(out)]


def audio_command(cfg: config.Config, monitor: str, out: Path) -> List[str]:
    """``ffmpeg``: the monitor of the sound output, as MP3. Never overwrites a file."""
    return [
        FFMPEG,
        "-hide_banner",
        "-loglevel",
        "error",
        "-n",
        "-f",
        "pulse",
        "-i",
        monitor,
        "-c:a",
        "libmp3lame",
        "-b:a",
        "%dk" % cfg.mp3_kbps,
        str(out),
    ]


def recording_path(folder: Path, mode: str, cfg: config.Config, now: datetime) -> Path:
    """``<folder>/2026-10-29_103000_video-audio.mkv``; a second recording in the same second gets
    ``-2`` before the extension."""
    extension = "mp3" if mode == AUDIO else cfg.container
    stem = "%s_%s" % (now.strftime("%Y-%m-%d_%H%M%S"), mode)
    path = folder / ("%s.%s" % (stem, extension))
    number = 2
    while path.exists():
        path = folder / ("%s-%d.%s" % (stem, number, extension))
        number += 1
    return path


def proc_identity(pid: int, proc_root: str = "/proc") -> Optional[Dict[str, object]]:
    """``{"comm", "state", "started"}`` of a pid from ``/proc/<pid>/stat``, ``None`` when there is
    no such process or the file cannot be read."""
    try:
        with open(
            os.path.join(proc_root, str(pid), "stat"), encoding="utf-8", errors="replace"
        ) as f:
            text = f.read()
    except OSError:
        return None
    left, right = text.find("("), text.rfind(")")
    if left < 0 or right < left:
        return None
    fields = text[right + 2 :].split()
    if len(fields) < 20:
        return None
    try:
        started = int(fields[19])
    except ValueError:
        return None
    return {"comm": text[left + 1 : right], "state": fields[0], "started": started}


def _default_notify(summary: str, body: str = "") -> None:
    try:
        subprocess.run(
            ["notify-send", "-a", APP_NAME, "-i", "media-record", summary, body],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        _LOG.warning("[notify] notify-send did not run: %s | %s", summary, body)


class Recorder:
    def __init__(
        self,
        env: Optional[Dict[str, str]] = None,
        popen: Callable[..., "subprocess.Popen[bytes]"] = subprocess.Popen,
        kill: Callable[[int, int], None] = os.kill,
        run: Callable[..., "subprocess.CompletedProcess[str]"] = subprocess.run,
        notify: Callable[[str, str], None] = _default_notify,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = datetime.now,
        proc_root: str = "/proc",
        start_check: float = START_CHECK_SECONDS,
        stop_wait: float = STOP_WAIT_SECONDS,
    ) -> None:
        self.env: Dict[str, str] = dict(os.environ if env is None else env)
        self.popen = popen
        self.kill = kill
        self.run = run
        self.notify = notify
        self.sleep = sleep
        self.now = now
        self.proc_root = proc_root
        self.start_check = start_check
        self.stop_wait = stop_wait

    # -- state ---------------------------------------------------------------------------------

    @property
    def dir(self) -> Path:
        return state_dir(self.env)

    @contextmanager
    def locked(self) -> Iterator[None]:
        with open(self.dir / "lock", "a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            yield

    def read_state(self) -> Optional[State]:
        """The recording that is running, or ``None``. A state file whose process is gone (a
        cancelled portal dialog, a crash, a reboot) is removed."""
        try:
            data = json.loads((self.dir / "state.json").read_text(encoding="utf-8"))
            state = State(
                pid=int(data["pid"]),
                started=int(data["started"]),
                mode=str(data["mode"]),
                file=str(data["file"]),
                paused=bool(data.get("paused", False)),
            )
        except (OSError, ValueError, KeyError, TypeError):
            return None
        if self.is_alive(state):
            return state
        self.clear_state()
        self._ended(state)
        return None

    def log_tail(self) -> str:
        """The end of the video recorder's log (empty when there is none)."""
        try:
            with open(self.dir / "recorder.log", "rb") as handle:
                handle.seek(0, os.SEEK_END)
                handle.seek(max(0, handle.tell() - _LOG_TAIL_BYTES))
                return handle.read().decode("utf-8", errors="replace")
        except OSError:
            return ""

    def _ended(self, state: State) -> None:
        """A recording whose recorder is gone without a stop command (the stop clears the state
        itself). When it died of an encoder failure, which with the portal can come well after
        the start (the screen is chosen first), the user is told what is missing; a cancelled
        screen choice or a sound recording ends quietly, as before."""
        if state.mode == AUDIO:
            return
        hint = encoder_problem(self.log_tail())
        if hint:
            _LOG.error("[recording] the recorder ended by itself: %s", hint)
            self.notify(_("The recording stopped"), "%s\n%s" % (hint, self.dir / "recorder.log"))

    def write_state(self, state: State) -> None:
        tmp = self.dir / ("state.json.%d.tmp" % os.getpid())
        tmp.write_text(json.dumps(asdict(state)), encoding="utf-8")
        os.replace(tmp, self.dir / "state.json")

    def clear_state(self) -> None:
        try:
            (self.dir / "state.json").unlink()
        except FileNotFoundError:
            pass

    def is_alive(self, state: State) -> bool:
        info = proc_identity(state.pid, self.proc_root)
        return bool(info) and info["started"] == state.started and info["state"] not in ("Z", "X")  # type: ignore[index]

    # -- commands ------------------------------------------------------------------------------

    def toggle(self, mode: str) -> int:
        """The key of ``mode``: stop and save what is recording, else start a recording."""
        if mode not in MODES:
            raise ValueError("unknown mode %r" % mode)
        with self.locked():
            state = self.read_state()
            return self._stop(state) if state else self._start(mode)

    def stop(self) -> int:
        with self.locked():
            state = self.read_state()
            return self._stop(state) if state else 0

    def pause(self) -> int:
        """Pause or resume. Nothing recording: nothing happens."""
        with self.locked():
            state = self.read_state()
            if not state:
                return 0
            audio = state.mode == AUDIO
            if audio:
                signal_number = signal.SIGCONT if state.paused else signal.SIGSTOP
            else:
                signal_number = signal.SIGUSR2
            try:
                self.kill(state.pid, signal_number)
            except OSError as error:
                _LOG.warning("[pause] signal %s to %d failed: %s", signal_number, state.pid, error)
                return 1
            state.paused = not state.paused
            self.write_state(state)
            return 0

    def status(self) -> Optional[State]:
        with self.locked():
            return self.read_state()

    # -- start ---------------------------------------------------------------------------------

    def default_monitor(self) -> str:
        try:
            result = self.run(
                ["pactl", "get-default-sink"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            result = None
        sink = result.stdout.strip() if result is not None and result.returncode == 0 else ""
        if not sink:
            raise RecorderError(_("Could not find the sound output to record"))
        return sink + ".monitor"

    def _start(self, mode: str) -> int:
        try:
            self._launch(mode)
        except RecorderError as error:
            _LOG.error("[start] %s", error)
            self.notify(_("Could not start the recording"), str(error))
            return 1
        return 0

    def target_folder(self, cfg: config.Config, mode: str) -> Path:
        """The folder this recording is saved in, made if it is not there yet. The one chosen for
        this kind of recording (video or sound) when it can be used (it exists or can be made, and
        is writable: a drive that is not plugged in is not); else the ``FOLDER`` of the settings,
        and when that cannot be made either, a ``RecorderError``."""
        default = cfg.folder_path(self.env)
        written = cfg.folder_for(mode == AUDIO)
        if written != cfg.folder:
            chosen = Path(config.expand(written, self.env))
            try:
                if chosen.is_absolute():
                    chosen.mkdir(parents=True, exist_ok=True)
                    if os.access(chosen, os.W_OK | os.X_OK):
                        return chosen
            except OSError:
                pass
            _LOG.warning("[folder] %s cannot be used, saving in %s", chosen, default)
        try:
            default.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise RecorderError(_("Could not create the folder %s") % default) from error
        return default

    def _launch(self, mode: str) -> None:
        cfg, warnings = config.load(self.env)
        for warning in warnings:
            _LOG.warning("[config] %s", warning)
        out = recording_path(self.target_folder(cfg, mode), mode, cfg, self.now())
        if mode == AUDIO:
            command = audio_command(cfg, self.default_monitor(), out)
        else:
            command = video_command(cfg, mode == VIDEO_AUDIO, out)
        log_path = self.dir / "recorder.log"
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
        log_fd = os.open(log_path, flags, 0o600)
        try:
            try:
                proc = self.popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=log_fd,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    close_fds=True,
                )
            except FileNotFoundError as error:
                raise RecorderError(_("%s is not installed") % command[0]) from error
            except OSError as error:
                raise RecorderError(_("%s did not start") % command[0]) from error
        finally:
            os.close(log_fd)
        waited = 0.0
        while waited < self.start_check:
            self.sleep(_TICK)
            waited += _TICK
            if proc.poll() is not None:
                raise RecorderError(self._start_failure(mode, log_path))
        info = proc_identity(proc.pid, self.proc_root)
        if info is None:
            raise RecorderError(self._start_failure(mode, log_path))
        self.write_state(
            State(pid=proc.pid, started=int(info["started"]), mode=mode, file=str(out))  # type: ignore[call-overload]
        )
        self.spawn_indicator()

    def _start_failure(self, mode: str, log_path: Path) -> str:
        """Why a recorder that ended at once did not start: the missing encoder driver when the
        log says so, else the log's place."""
        hint = encoder_problem(self.log_tail()) if mode != AUDIO else None
        if hint:
            return "%s\n%s" % (hint, log_path)
        return _("Could not start the recording (log: %s)") % log_path

    def spawn_indicator(self) -> None:
        """The red dot. It holds a lock, so a second one exits at once; it quits by itself when
        the recording is over. Its output goes to ``indicator.log`` (no tray, no GTK...)."""
        try:
            fd = os.open(
                self.dir / "indicator.log",
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
        except OSError as error:
            _LOG.warning("[indicator] no log file: %s", error)
            return
        try:
            self.popen(
                [sys.executable, "-m", "hotrec", "indicator"],
                stdin=subprocess.DEVNULL,
                stdout=fd,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
        except OSError as error:
            _LOG.warning("[indicator] did not start: %s", error)
        finally:
            os.close(fd)

    # -- stop ----------------------------------------------------------------------------------

    def _wait_gone(self, state: State, seconds: float) -> bool:
        waited = 0.0
        while self.is_alive(state):
            if waited >= seconds:
                return False
            self.sleep(_TICK)
            waited += _TICK
        return True

    def _send(self, state: State, signal_number: int) -> None:
        try:
            self.kill(state.pid, signal_number)
        except ProcessLookupError:
            pass

    def _stop(self, state: State) -> int:
        if state.paused:
            self._send(state, signal.SIGCONT)  # a stopped process cannot see SIGINT
        self._send(state, signal.SIGINT)
        clean = self._wait_gone(state, self.stop_wait)
        if not clean:
            _LOG.error("[stop] pid %d did not end after SIGINT, sending SIGTERM", state.pid)
            self._send(state, signal.SIGTERM)
            if not self._wait_gone(state, KILL_WAIT_SECONDS):
                self._send(state, signal.SIGKILL)
                self._wait_gone(state, KILL_WAIT_SECONDS)
        self.clear_state()
        if clean and Path(state.file).is_file():
            self.notify(_("Recording saved"), state.file)
            return 0
        self.notify(_("The recording may be incomplete"), state.file)
        return 1
