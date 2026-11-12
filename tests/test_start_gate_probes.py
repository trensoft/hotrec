# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

"""The two probes of the start gate (``tools/start_gate/probe_installed.py`` and
``probe_session.py``): what a failed step is, with stand-ins for the installed package, the
programs it runs and the desktop it talks to.

The probes run in the container of the gate, as root, against the installed package and a real GNOME
Shell. Here the same code runs against stand-ins, so that every way a step can be wrong is run: the
step must say FAIL, the run must end with 1, and a step that follows a failed one must not pass.
"""

from __future__ import annotations

import os
import subprocess
import sys
import types
from pathlib import Path

import pytest
from start_gate_helpers import GATE, stub


def _load(name):
    """The probe as a module. No ``__pycache__`` is written into ``tools/start_gate``, and none is
    read: a stale one (the same size, the same second) would run an older text of the script."""
    module = types.ModuleType(f"gate_{name}")
    module.__file__ = str(GATE / f"{name}.py")
    sys.modules[module.__name__] = module
    source = (GATE / f"{name}.py").read_text(encoding="utf-8")
    exec(compile(source, module.__file__, "exec"), module.__dict__)  # noqa: S102
    return module


def _done(code=0, out="", err=""):
    return subprocess.CompletedProcess([], code, out, err)


@pytest.fixture
def installed():
    return _load("probe_installed")


@pytest.fixture
def session_probe():
    return _load("probe_session")


# ---- probe_installed: main -------------------------------------------------------------------

STEPS = ("version", "import", "cli", "catalog", "tools")


def _patch_steps(monkeypatch, probe, broken=(), error=AssertionError("it is wrong")):
    def make(name):
        def step(*_args):
            if name in broken:
                raise error
            return f"{name} is fine"

        return step

    for name in STEPS:
        monkeypatch.setattr(probe, f"step_{name}", make(name))


def test_installed_passes_when_all_steps_pass(installed, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["probe_installed.py", "1.2.3"])
    _patch_steps(monkeypatch, installed)
    assert installed.main() == 0
    out = capsys.readouterr().out.splitlines()
    assert out == [f"START-GATE {name} PASS {name} is fine" for name in STEPS]


@pytest.mark.parametrize("failing", STEPS)
@pytest.mark.parametrize("error", [AssertionError("wrong"), ImportError("gone"), OSError("no")])
def test_installed_ends_with_1_when_one_step_fails_and_runs_the_others(
    installed, monkeypatch, capsys, failing, error
):
    monkeypatch.setattr(sys, "argv", ["probe_installed.py", "1.2.3"])
    _patch_steps(monkeypatch, installed, broken=(failing,), error=error)
    assert installed.main() == 1
    out = capsys.readouterr().out
    assert f"START-GATE {failing} FAIL {type(error).__name__}: {error}" in out
    assert out.count(" PASS ") == len(STEPS) - 1


def test_installed_wants_the_version(installed, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["probe_installed.py"])
    assert installed.main() == 2


def test_installed_gives_the_version_to_the_step_that_compares_it(installed, monkeypatch):
    seen = []
    monkeypatch.setattr(sys, "argv", ["probe_installed.py", "1.2.3"])
    _patch_steps(monkeypatch, installed)
    monkeypatch.setattr(installed, "step_version", lambda expected: seen.append(expected) or "ok")
    monkeypatch.setattr(installed, "step_cli", lambda expected: seen.append(expected) or "ok")
    installed.main()
    assert seen == ["1.2.3", "1.2.3"]


# ---- probe_installed: the steps --------------------------------------------------------------


def test_version_passes_for_the_version_of_the_package_in_the_system_prefix(installed, monkeypatch):
    import hotrec

    monkeypatch.setattr(installed.importlib.metadata, "version", lambda name: hotrec.__version__)
    monkeypatch.setattr(sys, "base_prefix", str(Path(hotrec.__file__).resolve().parents[2]))
    assert hotrec.__version__ in installed.step_version(hotrec.__version__)


def test_version_fails_when_the_metadata_has_another_version(installed, monkeypatch):
    import hotrec

    monkeypatch.setattr(installed.importlib.metadata, "version", lambda name: "0.0.1")
    monkeypatch.setattr(sys, "base_prefix", str(Path(hotrec.__file__).resolve().parents[2]))
    with pytest.raises(AssertionError, match="installed version 0.0.1"):
        installed.step_version(hotrec.__version__)


def test_version_fails_when_the_module_says_another_version(installed, monkeypatch):
    import hotrec

    monkeypatch.setattr(installed.importlib.metadata, "version", lambda name: "9.9.9")
    monkeypatch.setattr(sys, "base_prefix", str(Path(hotrec.__file__).resolve().parents[2]))
    with pytest.raises(AssertionError, match="hotrec.__version__ is"):
        installed.step_version("9.9.9")


def test_version_fails_for_a_checkout(installed, monkeypatch):
    """The package is imported from a directory outside the prefix: not the installed copy."""
    import hotrec

    monkeypatch.setattr(installed.importlib.metadata, "version", lambda name: hotrec.__version__)
    monkeypatch.setattr(sys, "base_prefix", "/nonexistent-prefix")
    with pytest.raises(AssertionError, match="not from /nonexistent-prefix"):
        installed.step_version(hotrec.__version__)


class _Toolkit:
    def __init__(self, major=3):
        self.major = major

    def get_major_version(self):
        return self.major

    @staticmethod
    def get_minor_version():
        return 24


def _fake_toolkit(monkeypatch, major=3, error=None):
    from hotrec import indicator

    def load():
        if error:
            raise error
        glib = types.SimpleNamespace(MAJOR_VERSION=2, MINOR_VERSION=80)
        return _Toolkit(major), glib, types.SimpleNamespace(__name__="AyatanaAppIndicator3")

    monkeypatch.setattr(indicator, "_load_toolkit", load)


def test_import_passes_with_gtk_3(installed, monkeypatch):
    _fake_toolkit(monkeypatch)
    text = installed.step_import()
    assert "modules import; Gtk 3.24, AyatanaAppIndicator3, GLib 2.80" in text


def test_import_fails_with_another_gtk(installed, monkeypatch):
    _fake_toolkit(monkeypatch, major=4)
    with pytest.raises(AssertionError, match="Gtk 4"):
        installed.step_import()


@pytest.mark.parametrize("error", [ImportError("no gi"), ValueError("no Gtk 3.0")])
def test_import_fails_when_the_toolkit_does_not_load(installed, monkeypatch, error):
    _fake_toolkit(monkeypatch, error=error)
    with pytest.raises(type(error)):
        installed.step_import()


def test_import_fails_when_a_module_does_not_import(installed, monkeypatch):
    _fake_toolkit(monkeypatch)
    real = installed.importlib.import_module

    def broken(name, *args):
        if name == "hotrec.shellext":
            raise ImportError("broken module")
        return real(name, *args)

    monkeypatch.setattr(installed.importlib, "import_module", broken)
    with pytest.raises(ImportError, match="broken module"):
        installed.step_import()


def test_import_fails_when_hardly_any_module_is_found(installed, monkeypatch):
    _fake_toolkit(monkeypatch)
    monkeypatch.setattr(installed.pkgutil, "iter_modules", lambda path: [])
    with pytest.raises(AssertionError, match="only 0 modules found"):
        installed.step_import()


def _cli(
    monkeypatch,
    probe,
    command="/usr/bin/hotrec",
    version="hotrec 1.2.3\n",
    status=(1, "not recording\n"),
):
    monkeypatch.setattr(probe.shutil, "which", lambda name: command)

    def run(cmd, **kwargs):
        if cmd[1] == "--version":
            return _done(0, version)
        assert cmd[1] == "status"
        return _done(status[0], status[1])

    monkeypatch.setattr(probe, "_run", run)


def test_cli_passes(installed, monkeypatch):
    _cli(monkeypatch, installed)
    assert "hotrec 1.2.3" in installed.step_cli("1.2.3")


@pytest.mark.parametrize("command", [None, "", "/usr/local/bin/hotrec", "/tmp/hotrec"])
def test_cli_fails_when_the_command_is_not_the_installed_one(installed, monkeypatch, command):
    _cli(monkeypatch, installed, command=command)
    with pytest.raises(AssertionError, match="not the installed /usr/bin/hotrec"):
        installed.step_cli("1.2.3")


@pytest.mark.parametrize("version", ["hotrec 1.2.4\n", "", "hotrec1.2.3\n", "1.2.3\n"])
def test_cli_fails_when_the_command_says_another_version(installed, monkeypatch, version):
    _cli(monkeypatch, installed, version=version)
    with pytest.raises(AssertionError, match="hotrec --version"):
        installed.step_cli("1.2.3")


@pytest.mark.parametrize(
    "status", [(0, "not recording\n"), (2, "not recording\n"), (1, ""), (1, "audio /x.mp3\n")]
)
def test_cli_fails_when_status_is_not_one_with_not_recording(installed, monkeypatch, status):
    _cli(monkeypatch, installed, status=status)
    with pytest.raises(AssertionError, match="hotrec status"):
        installed.step_cli("1.2.3")


def test_cli_fails_when_the_version_command_fails_with_the_right_text(installed, monkeypatch):
    monkeypatch.setattr(installed.shutil, "which", lambda name: "/usr/bin/hotrec")
    monkeypatch.setattr(installed, "_run", lambda cmd, **kw: _done(3, "hotrec 1.2.3\n"))
    with pytest.raises(AssertionError, match="hotrec --version"):
        installed.step_cli("1.2.3")


class _Status:
    def __init__(self, catalogs, localedir="/usr/share/locale"):
        self.catalogs = catalogs
        self.localedir = localedir


def _catalog(monkeypatch, probe, catalogs, translated="Leállítás és mentés"):
    import gettext

    from hotrec import i18n

    monkeypatch.setattr(i18n, "setup", lambda: _Status(catalogs))
    monkeypatch.setattr(gettext, "gettext", lambda text: translated if translated else text)
    monkeypatch.delenv("LANGUAGE", raising=False)


GOOD_MO = ("/usr/share/locale/hu/LC_MESSAGES/io.github.trensoft.hotrec.mo",)


def test_catalog_passes(installed, monkeypatch):
    _catalog(monkeypatch, installed, GOOD_MO)
    assert "Leállítás és mentés" in installed.step_catalog()


def test_catalog_asks_for_hungarian(installed, monkeypatch):
    import os

    _catalog(monkeypatch, installed, GOOD_MO)
    installed.step_catalog()
    assert os.environ["LANGUAGE"] == "hu"
    monkeypatch.delenv("LANGUAGE")


def test_catalog_fails_when_none_is_found(installed, monkeypatch):
    _catalog(monkeypatch, installed, ())
    with pytest.raises(AssertionError, match="no catalog found"):
        installed.step_catalog()


def test_catalog_fails_for_a_catalog_of_another_language(installed, monkeypatch):
    _catalog(
        monkeypatch, installed, ("/usr/share/locale/de/LC_MESSAGES/io.github.trensoft.hotrec.mo",)
    )
    with pytest.raises(AssertionError, match="none ends with"):
        installed.step_catalog()


@pytest.mark.parametrize("translated", ["Stop and save", ""])
def test_catalog_fails_when_the_text_is_not_translated(installed, monkeypatch, translated):
    _catalog(monkeypatch, installed, GOOD_MO, translated="Stop and save")
    with pytest.raises(AssertionError, match="is not translated"):
        installed.step_catalog()


class _Programs:
    """Which programs are installed and what they answer, for ``step_tools``."""

    def __init__(
        self,
        monkeypatch,
        probe,
        missing=(),
        ldd_out="",
        ldd_rc=0,
        encoders="libmp3lame\n",
        encoders_rc=0,
        fails=(),
    ):
        self.calls = []

        def which(name):
            return None if name in missing else f"/usr/bin/{name}"

        def run(cmd, **kwargs):
            self.calls.append(cmd)
            name = cmd[0].rsplit("/", 1)[-1]
            if name == "ldd":
                return _done(ldd_rc, ldd_out)
            if name == "ffmpeg":
                return _done(encoders_rc, encoders)
            return _done(1 if name in fails else 0, "x 1.0\n")

        monkeypatch.setattr(probe.shutil, "which", which)
        monkeypatch.setattr(probe, "_run", run)


def test_tools_pass(installed, monkeypatch):
    programs = _Programs(monkeypatch, installed)
    text = installed.step_tools()
    assert text == (
        "gpu-screen-recorder linked, ffmpeg has libmp3lame, pactl runs, notify-send runs"
    )
    assert ["ldd", "/usr/bin/gpu-screen-recorder"] in programs.calls


@pytest.mark.parametrize("name", ["gpu-screen-recorder", "ffmpeg", "pactl", "notify-send", "ldd"])
def test_tools_fail_for_a_missing_program(installed, monkeypatch, name):
    _Programs(monkeypatch, installed, missing=(name,))
    with pytest.raises(AssertionError, match=name):
        installed.step_tools()


def test_tools_fail_for_a_library_that_is_not_found(installed, monkeypatch):
    _Programs(monkeypatch, installed, ldd_out="\tlibx.so.1 => not found\n\tlibc.so.6 => /lib\n")
    with pytest.raises(AssertionError, match="libx.so.1"):
        installed.step_tools()


def test_tools_fail_when_ldd_fails(installed, monkeypatch):
    _Programs(monkeypatch, installed, ldd_rc=1)
    with pytest.raises(AssertionError, match="ldd"):
        installed.step_tools()


@pytest.mark.parametrize("encoders, rc", [("aac\n", 0), ("libmp3lame\n", 1), ("", 127)])
def test_tools_fail_when_ffmpeg_has_no_mp3_encoder_or_does_not_run(
    installed, monkeypatch, encoders, rc
):
    _Programs(monkeypatch, installed, encoders=encoders, encoders_rc=rc)
    with pytest.raises(AssertionError, match="ffmpeg -encoders"):
        installed.step_tools()


@pytest.mark.parametrize("name", ["pactl", "notify-send"])
def test_tools_fail_when_a_helper_does_not_run(installed, monkeypatch, name):
    _Programs(monkeypatch, installed, fails=(name,))
    with pytest.raises(AssertionError, match=f"{name} --version"):
        installed.step_tools()


# ---- probe_session: main ---------------------------------------------------------------------


class _FakeSession:
    """The ``Session`` of the probe with steps that pass or fail as told (``FAILING``)."""

    FAILING = ()
    instances = []

    def __init__(self, tmp, timeout):
        self.timeout = timeout
        self.stopped = False
        self.logs_printed = False
        _FakeSession.instances.append(self)

    def __getattr__(self, name):
        if not name.startswith("step_"):
            raise AttributeError(name)

        def step():
            if name[5:] in _FakeSession.FAILING:
                raise RuntimeError(f"{name} went wrong")
            return f"{name} is fine"

        return step

    def stop(self):
        self.stopped = True

    def print_logs(self):
        self.logs_printed = True
        print("--- logs")


@pytest.fixture
def fake_session(session_probe, monkeypatch):
    _FakeSession.FAILING = ()
    _FakeSession.instances = []
    monkeypatch.setattr(session_probe, "Session", _FakeSession)
    monkeypatch.setattr(sys, "argv", ["probe_session.py"])
    return _FakeSession


SESSION_STEPS = ("shell", "loaded", "autostart", "extension", "dot", "windows", "single", "quit")
# the steps that do not run after a failed one, with the one they need
NEEDS = {
    "loaded": "shell",
    "autostart": "shell",
    "extension": "autostart",
    "dot": "autostart",
    "windows": "dot",
    "single": "dot",
    "quit": "dot",
}


def test_session_steps_are_these_in_this_order(session_probe):
    assert session_probe.STEPS == SESSION_STEPS


def test_session_passes_when_all_steps_pass(session_probe, fake_session, capsys):
    assert session_probe.main() == 0
    out = capsys.readouterr().out.splitlines()
    assert out == [f"START-GATE {name} PASS step_{name} is fine" for name in SESSION_STEPS]
    assert fake_session.instances[0].stopped and not fake_session.instances[0].logs_printed


def _dependents(step):
    """The steps that do not run when ``step`` failed: those that need it, and what needs them."""
    out = []
    for name in SESSION_STEPS:
        if NEEDS.get(name) == step or NEEDS.get(name) in out:
            out.append(name)
    return out


@pytest.mark.parametrize("failing", SESSION_STEPS)
def test_session_ends_with_1_and_skips_only_what_depends_on_a_failed_step(
    session_probe, fake_session, capsys, failing
):
    fake_session.FAILING = (failing,)
    assert session_probe.main() == 1
    out = capsys.readouterr().out.splitlines()
    skipped = _dependents(failing)
    for name in SESSION_STEPS:
        line = [ln for ln in out if ln.startswith(f"START-GATE {name} ")]
        assert len(line) == 1, (name, out)
        if name == failing:
            assert line[0] == f"START-GATE {name} FAIL RuntimeError: step_{name} went wrong"
        elif name in skipped:
            assert line[0].startswith(f"START-GATE {name} FAIL not run: the step ")
        else:
            assert line[0] == f"START-GATE {name} PASS step_{name} is fine", line
    assert fake_session.instances[0].logs_printed and fake_session.instances[0].stopped
    assert "--- logs" in out


def test_session_names_the_step_that_a_skipped_step_needed(session_probe, fake_session, capsys):
    fake_session.FAILING = ("autostart",)
    session_probe.main()
    out = capsys.readouterr().out
    assert "START-GATE dot FAIL not run: the step autostart failed" in out
    assert "START-GATE windows FAIL not run: the step dot failed" in out


def test_a_skipped_step_is_a_failure_even_when_nothing_else_is(session_probe, fake_session, capsys):
    """The exit status is 1 for a failed step, and a skipped step is one."""
    fake_session.FAILING = ("shell",)
    assert session_probe.main() == 1
    out = capsys.readouterr().out
    assert " PASS " not in out


def test_the_session_needs_table_is_the_one_documented(session_probe):
    assert {k: v[0] for k, v in session_probe.NEEDS.items()} == NEEDS
    assert all(len(v) == 1 for v in session_probe.NEEDS.values())


def test_session_stops_its_children_also_when_a_step_raises_an_exception_that_is_not_an_error(
    session_probe, fake_session, monkeypatch
):
    class Interrupt(BaseException):
        pass

    def step_shell(self):
        raise Interrupt()

    monkeypatch.setattr(fake_session, "step_shell", step_shell, raising=False)
    with pytest.raises(Interrupt):
        session_probe.main()
    assert fake_session.instances[0].stopped


def test_session_takes_the_timeout_from_the_command_line(session_probe, fake_session, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["probe_session.py", "--timeout", "7"])
    session_probe.main()
    assert fake_session.instances[0].timeout == 7


# ---- probe_session: the steps ----------------------------------------------------------------


@pytest.fixture
def session(session_probe, tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path / "bin") + ":/usr/bin:/bin")
    (tmp_path / "bin").mkdir()
    return session_probe.Session(str(tmp_path / "s"), 1)


def _gdbus(tmp_path, body):
    stub(tmp_path / "bin" / "gdbus", body)


@pytest.mark.parametrize(
    "answer, state",
    [
        ("({'uuid': <'x'>, 'state': <1.0>, 'path': <'/p'>},)", 1),
        ("({'state': <double 2>},)", 2),
        ("({'state': <uint32 6>},)", 6),
        ("({'state': <int32 4>, 'error': <''>},)", 4),
        ("({'uuid': <'x'>, 'state': <8.0>},)", 8),
    ],
)
def test_extension_state_reads_the_state_in_every_form_of_the_answer(
    tmp_path, session, answer, state
):
    _gdbus(tmp_path, f'echo "{answer}"\n')
    assert session.extension_state()[0] == state


@pytest.mark.parametrize("answer, code", [("({},)", 0), ("", 0), ("({'state': <1.0>},)", 1)])
def test_extension_state_is_none_for_an_empty_answer_or_a_failed_call(
    tmp_path, session, answer, code
):
    _gdbus(tmp_path, f'echo "{answer}"; exit {code}\n')
    assert session.extension_state()[0] is None


def test_extension_state_asks_the_extension_service_about_the_uuid(tmp_path, session):
    _gdbus(tmp_path, 'echo "$@" > "$0.args"; echo "({\'state\': <1.0>},)"\n')
    session.extension_state()
    args = (tmp_path / "bin" / "gdbus.args").read_text(encoding="utf-8")
    assert "--dest org.gnome.Shell.Extensions" in args
    assert "org.gnome.Shell.Extensions.GetExtensionInfo hotrec-dot@trensoft.github.io" in args


def test_registered_reads_the_service_of_the_item_from_the_log_of_the_desktop(session):
    Path(session.desktop_log).parent.mkdir(parents=True, exist_ok=True)
    Path(session.desktop_log).write_text(
        "NOTIFY Hotrec | a | b\nITEM-REGISTERED :1.5/org/ayatana/x (from :1.5)\n", encoding="utf-8"
    )
    assert session._registered() == ":1.5/org/ayatana/x"


def test_registered_is_empty_before_the_item_registers(session):
    assert session._registered() == ""
    Path(session.desktop_log).parent.mkdir(parents=True, exist_ok=True)
    Path(session.desktop_log).write_text("NOTIFY Hotrec | a | b\n", encoding="utf-8")
    assert session._registered() == ""


def test_wait_for_raises_when_the_check_never_holds(session_probe, session, monkeypatch):
    monkeypatch.setattr(session_probe.time, "sleep", lambda seconds: None)
    clock = iter(range(0, 1000, 1))
    monkeypatch.setattr(session_probe.time, "monotonic", lambda: next(clock))
    with pytest.raises(session_probe.Failed, match="never: not after 1 s"):
        session.wait_for("never", lambda: False)


def test_wait_for_returns_what_the_check_returns(session_probe, session, monkeypatch):
    monkeypatch.setattr(session_probe.time, "sleep", lambda seconds: None)
    answers = iter([None, "", "found"])
    assert session.wait_for("x", lambda: next(answers)) == "found"


class _Proc:
    """A child process: running until ``code`` is set; ``wait`` answers with it."""

    def __init__(self, code=None, wait_code=0, wait_raises=False):
        self.code = code
        self.wait_code = wait_code
        self.wait_raises = wait_raises
        self.events = []

    def poll(self):
        return self.code

    @property
    def returncode(self):
        return self.code

    def wait(self, timeout=None):
        if self.wait_raises and "kill" not in self.events:
            raise subprocess.TimeoutExpired("x", timeout)
        self.code = self.wait_code
        return self.code

    def terminate(self):
        self.events.append("terminate")

    def kill(self):
        self.events.append("kill")
        self.code = -9


def _write(path, text):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text, encoding="utf-8")


KEYS_LINES = "\n".join(
    "%-15s %s" % (keys, "/usr/bin/hotrec " + mode)
    for keys, mode in (
        ("Ctrl+Shift+F9", "video-audio"),
        ("Ctrl+Shift+F10", "video"),
        ("Ctrl+Shift+F11", "audio"),
        ("Ctrl+Shift+F12", "pause"),
        ("Ctrl+Shift+F7", "region-video-audio"),
        ("Ctrl+Shift+F8", "region-video"),
    )
)
DESKTOP_OK = (
    "NOTIFY Hotrec | Keyboard shortcuts are set | Ctrl+Shift+F9: screen and sound.\n"
    "NOTIFY Hotrec | Hotrec | The blinking red dot over a fullscreen video is on. "
    "You can turn it off in the Extensions app.\n"
    "ITEM-REGISTERED :1.7/org/ayatana/NotificationItem/io_github_trensoft_hotrec (from :1.7)\n"
)


def _autostart(
    session, session_probe, monkeypatch, desktop=DESKTOP_OK, proc=None, status=(0, KEYS_LINES)
):
    monkeypatch.setattr(session_probe.time, "sleep", lambda seconds: None)
    _write(session.desktop_log, desktop)
    session.spawn = lambda command, log, **kwargs: proc or _Proc()
    session.hotrec = lambda *args, **kwargs: _done(status[0], status[1])
    session.wait_for = lambda what, check, timeout=None: check()


def test_autostart_passes(session, session_probe, monkeypatch):
    _autostart(session, session_probe, monkeypatch)
    text = session.step_autostart()
    assert "Keyboard shortcuts are set" in text and "Ctrl+Shift+F12" in text


def test_autostart_runs_the_installed_command_with_the_autostart_argument(
    session, session_probe, monkeypatch
):
    _autostart(session, session_probe, monkeypatch)
    seen = []
    session.spawn = lambda command, log, **kwargs: seen.append((command, log)) or _Proc()
    session.step_autostart()
    assert seen == [(["hotrec", "autostart"], session.program_log)]


def test_autostart_fails_when_the_program_ends_before_the_dot(session, session_probe, monkeypatch):
    _autostart(session, session_probe, monkeypatch, desktop="", proc=_Proc(code=1))
    _write(session.program_log, "Traceback (most recent call last):\nAttributeError: x\n")
    with pytest.raises(
        session_probe.Failed, match="ended with status 1 at its start.*AttributeError"
    ):
        session.step_autostart()


def test_autostart_waits_a_second_after_the_dot_before_it_looks_at_the_program(
    session, session_probe, monkeypatch
):
    """A program that dies right after it registered the dot is not a start: the check that the
    program still runs is made a second later, not at once."""
    _autostart(session, session_probe, monkeypatch)
    order = []
    monkeypatch.setattr(
        session_probe.time, "sleep", lambda seconds: order.append(("sleep", seconds))
    )
    proc = _Proc()
    original = proc.poll
    proc.poll = lambda: order.append(("poll", None)) or original()
    session.spawn = lambda command, log, **kwargs: proc
    session.step_autostart()
    assert order[:2] == [("sleep", 1), ("poll", None)]


def test_autostart_fails_when_the_program_ends_right_after_it_registered_the_dot(
    session, session_probe, monkeypatch
):
    """The dot is there in the log and the process is gone: that is not a start."""
    _autostart(session, session_probe, monkeypatch, proc=_Proc(code=1))
    with pytest.raises(session_probe.Failed, match="ended with status 1 at its start"):
        session.step_autostart()


def test_autostart_fails_without_the_notification_about_the_shortcuts(
    session, session_probe, monkeypatch
):
    desktop = "ITEM-REGISTERED :1.7/org/x (from :1.7)\n"
    _autostart(session, session_probe, monkeypatch, desktop=desktop)
    with pytest.raises(session_probe.Failed, match="no notification 'Keyboard shortcuts are set'"):
        session.step_autostart()


@pytest.mark.parametrize(
    "status",
    [
        (1, KEYS_LINES),
        (0, "\n".join(KEYS_LINES.splitlines()[:5])),
        (0, KEYS_LINES + "\nCtrl+Shift+F6    /usr/bin/hotrec x"),
        (0, KEYS_LINES.replace("/usr/bin/hotrec pause", "not set")),
        (0, KEYS_LINES.replace("/usr/bin/hotrec video-audio", "/usr/bin/other video-audio")),
    ],
)
def test_autostart_fails_when_the_shortcuts_are_not_read_back(
    session, session_probe, monkeypatch, status
):
    _autostart(session, session_probe, monkeypatch, status=status)
    with pytest.raises(session_probe.Failed, match="shortcut"):
        session.step_autostart()


def _extension(session, session_probe, monkeypatch, states, desktop=DESKTOP_OK, shell_log=""):
    monkeypatch.setattr(session_probe.time, "sleep", lambda seconds: None)
    _write(session.desktop_log, desktop)
    _write(session.shell_log, shell_log)
    answers = iter(states)
    session.extension_state = lambda: (next(answers), "info")
    calls = []

    def wait_for(what, check, timeout=None):
        calls.append(what)
        if not check():
            raise session_probe.Failed(what)
        return True

    session.wait_for = wait_for
    return calls


def test_extension_passes_when_the_shell_enables_it(session, session_probe, monkeypatch):
    _extension(session, session_probe, monkeypatch, [1])
    assert "ENABLED" in session.step_extension()


@pytest.mark.parametrize("state", [2, 3, 4, 6, None])
def test_extension_fails_when_the_state_is_not_enabled(session, session_probe, monkeypatch, state):
    _extension(session, session_probe, monkeypatch, [state, state])
    with pytest.raises(session_probe.Failed, match="not ENABLED"):
        session.step_extension()


@pytest.mark.parametrize("desktop", [DESKTOP_OK.replace("The blinking", "A"), DESKTOP_OK * 2])
def test_extension_wants_exactly_one_notification_about_it(
    session, session_probe, monkeypatch, desktop
):
    _extension(session, session_probe, monkeypatch, [1], desktop=desktop)
    with pytest.raises(session_probe.Failed, match="expected one notification about the extension"):
        session.step_extension()


def test_extension_fails_when_hotrec_did_not_see_that_the_shell_knows_it(
    session, session_probe, monkeypatch
):
    desktop = DESKTOP_OK.replace(
        "You can turn", "If you do not see it yet, log out and in once. You can turn"
    )
    _extension(session, session_probe, monkeypatch, [1], desktop=desktop)
    with pytest.raises(
        session_probe.Failed, match="did not see that the Shell knows the extension"
    ):
        session.step_extension()


@pytest.mark.parametrize(
    "line",
    [
        "JS ERROR: Extension hotrec-dot@trensoft.github.io: TypeError: x",
        "GNOME Shell-CRITICAL **: hotrec-dot@trensoft.github.io broke",
        "Gjs-Message: hotrec extension threw an Exception",
    ],
)
def test_extension_fails_when_the_shell_logged_an_error_about_it(
    session, session_probe, monkeypatch, line
):
    _extension(session, session_probe, monkeypatch, [1], shell_log="fine line\n" + line + "\n")
    with pytest.raises(session_probe.Failed, match="the Shell logged errors about the extension"):
        session.step_extension()


def test_extension_ignores_errors_that_are_not_about_it(session, session_probe, monkeypatch):
    log = "GNOME Shell-CRITICAL **: the calendar server is missing\nhotrec-dot loaded\n"
    _extension(session, session_probe, monkeypatch, [1], shell_log=log)
    assert session.step_extension()


class _Reply:
    def __init__(self, value):
        self.value = value

    def unpack(self):
        return self.value


MENU_ROWS = [
    ("Record screen and sound (Ctrl+Shift+F9)", True),
    ("Record screen only (Ctrl+Shift+F10)", True),
    ("Record sound only (Ctrl+Shift+F11)", True),
    ("Record area and sound (Ctrl+Shift+F7)", True),
    ("Record area only (Ctrl+Shift+F8)", True),
    ("Pause (Ctrl+Shift+F12)", False),
    ("Stop and save", False),
    ("Settings…", True),
    ("About", True),
    ("Quit", True),
]
PROPS = {"Id": "io.github.trensoft.hotrec", "Status": "Active", "IconName": "x-symbolic"}


def _dot(session, session_probe, monkeypatch, rows=None, props=None, registered=True):
    _write(
        session.desktop_log,
        "ITEM-REGISTERED :1.7/org/ayatana/NotificationItem/io_github_trensoft_hotrec (from :1.7)\n"
        if registered
        else "",
    )
    session._connection = lambda: object()
    session._call = lambda conn, path, iface, method, args, signature: _Reply((props or PROPS,))
    shown = MENU_ROWS if rows is None else rows
    session._menu = lambda conn: (
        "/menu",
        {label: (number + 2, enabled) for number, (label, enabled) in enumerate(shown)},
    )


def test_dot_passes_and_keeps_the_ids_of_the_rows_for_the_next_steps(
    session, session_probe, monkeypatch
):
    _dot(session, session_probe, monkeypatch)
    assert "menu of 10 rows" in session.step_dot()
    assert session.rows["Quit"] == (11, True) and session.menu_path == "/menu"
    assert session.item == ":1.7/org/ayatana/NotificationItem/io_github_trensoft_hotrec"


def test_dot_fails_when_it_did_not_register(session, session_probe, monkeypatch):
    _dot(session, session_probe, monkeypatch, registered=False)
    with pytest.raises(session_probe.Failed, match="did not register"):
        session.step_dot()


@pytest.mark.parametrize(
    "props",
    [
        {**PROPS, "Id": "other"},
        {**PROPS, "Status": "Passive"},
        {**PROPS, "Status": "NeedsAttention"},
    ],
)
def test_dot_fails_for_another_item_or_an_item_that_is_not_active(
    session, session_probe, monkeypatch, props
):
    _dot(session, session_probe, monkeypatch, props=props)
    with pytest.raises(session_probe.Failed, match="the dot is"):
        session.step_dot()


@pytest.mark.parametrize(
    "rows",
    [
        MENU_ROWS[:-1],  # no Quit
        MENU_ROWS + [("More", True)],
        MENU_ROWS[1:] + MENU_ROWS[:1],  # another order
        [(label.split(" (")[0], enabled) for label, enabled in MENU_ROWS],  # no keys in the rows
        [(label, not enabled if label == "Quit" else enabled) for label, enabled in MENU_ROWS],
        [(label, True if label == "Stop and save" else enabled) for label, enabled in MENU_ROWS],
        [],
    ],
)
def test_dot_fails_for_another_menu(session, session_probe, monkeypatch, rows):
    _dot(session, session_probe, monkeypatch, rows=rows)
    with pytest.raises(session_probe.Failed, match="the menu of the dot is"):
        session.step_dot()


def test_the_menu_is_the_menu_of_the_resident_dot(session_probe):
    assert session_probe.MENU == MENU_ROWS
    assert len(session_probe.KEYS) == 6


def test_menu_reads_the_rows_of_the_dbusmenu_layout(session):
    session.item = ":1.7/org/ayatana/x"
    layout = (
        0,
        {},
        [
            (2, {"label": "A"}, []),
            (3, {"label": "B", "enabled": False}, []),
            (4, {"type": "separator"}, []),
        ],
    )

    def call(conn, path, iface, method, args, signature):
        if method == "Get":
            return _Reply(("/org/ayatana/x/Menu",))
        assert (method, args) == ("GetLayout", (0, -1, []))
        return _Reply((1, layout))

    session._call = call
    menu_path, rows = session._menu(object())
    assert menu_path == "/org/ayatana/x/Menu"
    assert rows == {"A": (2, True), "B": (3, False)}


def _clicking(session, session_probe, monkeypatch, proc, log=""):
    monkeypatch.setattr(session_probe.time, "sleep", lambda seconds: None)
    session.program = proc
    session.menu_path = "/menu"
    session.rows = {
        label: (number + 2, enabled) for number, (label, enabled) in enumerate(MENU_ROWS)
    }
    session._connection = lambda: object()
    clicks = []
    session._click = lambda conn, path, number: clicks.append((path, number))
    _write(session.program_log, log)
    return clicks


def test_windows_clicks_about_and_settings_and_the_program_survives(
    session, session_probe, monkeypatch
):
    clicks = _clicking(session, session_probe, monkeypatch, _Proc())
    assert "still running" in session.step_windows()
    assert clicks == [("/menu", session.rows["About"][0]), ("/menu", session.rows["Settings…"][0])]


def test_windows_fails_when_the_program_ends_after_a_click(session, session_probe, monkeypatch):
    _clicking(session, session_probe, monkeypatch, _Proc(code=1))
    with pytest.raises(session_probe.Failed, match="ended with status 1 after 'About'"):
        session.step_windows()


def test_windows_fails_for_a_traceback_in_the_log(session, session_probe, monkeypatch):
    _clicking(
        session, session_probe, monkeypatch, _Proc(), log="Traceback (most recent call last):\n"
    )
    with pytest.raises(session_probe.Failed, match="traceback after opening the windows"):
        session.step_windows()


def test_single_passes_when_the_second_one_ends_with_0_and_adds_no_dot(
    session, session_probe, monkeypatch
):
    _write(session.desktop_log, DESKTOP_OK)
    session.hotrec = lambda *args, **kwargs: _done(0)
    assert "no second dot" in session.step_single()


def test_single_asks_for_autostart(session, session_probe, monkeypatch):
    _write(session.desktop_log, DESKTOP_OK)
    seen = []
    session.hotrec = lambda *args, **kwargs: seen.append(args) or _done(0)
    session.step_single()
    assert seen == [("autostart",)]


def test_single_fails_when_the_second_one_ends_with_an_error(session, session_probe, monkeypatch):
    _write(session.desktop_log, DESKTOP_OK)
    session.hotrec = lambda *args, **kwargs: _done(1, "", "boom")
    with pytest.raises(session_probe.Failed, match="ended with status 1"):
        session.step_single()


def test_single_fails_when_a_second_dot_is_registered(session, session_probe, monkeypatch):
    _write(session.desktop_log, DESKTOP_OK)

    def second(*args, **kwargs):
        with open(session.desktop_log, "a", encoding="utf-8") as handle:
            handle.write("ITEM-REGISTERED :1.9/org/y (from :1.9)\n")
        return _done(0)

    session.hotrec = second
    with pytest.raises(session_probe.Failed, match="a second dot was registered \\(1 -> 2\\)"):
        session.step_single()


def test_quit_passes_when_the_program_ends_with_0(session, session_probe, monkeypatch):
    clicks = _clicking(session, session_probe, monkeypatch, _Proc(wait_code=0))
    assert "status 0" in session.step_quit()
    assert clicks == [("/menu", session.rows["Quit"][0])]


@pytest.mark.parametrize("code", [1, 2, -15, 143])
def test_quit_fails_when_the_program_ends_with_another_status(
    session, session_probe, monkeypatch, code
):
    _clicking(session, session_probe, monkeypatch, _Proc(wait_code=code))
    with pytest.raises(session_probe.Failed, match=f"ended with status {code} after Quit, not 0"):
        session.step_quit()


def test_quit_fails_when_the_program_does_not_end(session, session_probe, monkeypatch):
    _clicking(session, session_probe, monkeypatch, _Proc(wait_raises=True))
    with pytest.raises(session_probe.Failed, match="did not end 30 s after Quit"):
        session.step_quit()


def test_quit_fails_for_a_traceback_in_the_log(session, session_probe, monkeypatch):
    _clicking(
        session,
        session_probe,
        monkeypatch,
        _Proc(wait_code=0),
        log="Traceback (most recent call last):\n",
    )
    with pytest.raises(session_probe.Failed, match="a traceback in the log of the program"):
        session.step_quit()


def _shell(session, session_probe, monkeypatch, login_code=None, version="49.10"):
    session.start_bus = lambda name, services: f"unix:path=/{name}"
    procs = []

    def spawn(command, log, **kwargs):
        proc = _Proc(code=login_code if "fake_login1" in " ".join(command) else None)
        procs.append((command, proc))
        return proc

    session.spawn = spawn
    answers = iter([True, version])
    session.wait_for = lambda what, check, timeout=None: next(answers)
    return procs


def test_shell_passes_when_the_shell_answers(session, session_probe, monkeypatch):
    procs = _shell(session, session_probe, monkeypatch)
    assert session.step_shell() == "GNOME Shell 49.10 is up"
    assert session.shell_version == "49.10"
    started = [" ".join(command) for command, _ in procs]
    assert any("gnome-shell --headless --wayland --no-x11" in line for line in started)
    assert any("fake_login1.py" in line for line in started)
    assert any("fake_desktop.py" in line for line in started)


def test_shell_fails_when_the_fake_logind_ends_at_once(session, session_probe, monkeypatch):
    _shell(session, session_probe, monkeypatch, login_code=1)
    with pytest.raises(session_probe.Failed, match="fake_login1.py ended at once"):
        session.step_shell()


def _loaded(session, session_probe, answers):
    session.shell_version = "50.6"
    states = iter(answers)
    session.extension_state = lambda: next(states)
    session.wait_for = lambda what, check, timeout=None: check()


@pytest.mark.parametrize("state", [1, 2, 6, 7, 8])
def test_loaded_passes_for_the_states_of_a_usable_extension(session, session_probe, state):
    _loaded(session, session_probe, [(state, "info")])
    assert session.step_loaded() == (
        f"GNOME Shell 50.6 knows hotrec-dot@trensoft.github.io, state {state}"
    )


@pytest.mark.parametrize("state", [3, 4, 5, 99])
def test_loaded_fails_when_the_extension_is_not_loaded(session, session_probe, state):
    """State 4 is OUT_OF_DATE: the Shell does not know this extension for its own version."""
    _loaded(session, session_probe, [(state, "info of it")])
    with pytest.raises(
        session_probe.Failed,
        match=f"GNOME Shell 50.6 has the extension in state {state}, not a loaded",
    ):
        session.step_loaded()


def test_loaded_fails_when_the_shell_does_not_know_the_extension(session, session_probe):
    _loaded(session, session_probe, [(None, "empty")])
    session.wait_for = lambda what, check, timeout=None: (
        check() or (_ for _ in ()).throw(session_probe.Failed(what))
    )
    session.extension_state = lambda: (None, "({},)")
    with pytest.raises(
        session_probe.Failed, match=r"does not know the extension.*GetExtensionInfo"
    ):
        session.step_loaded()


def test_the_loaded_states_are_those_of_a_usable_extension(session_probe):
    assert session_probe.LOADED_STATES == {1, 2, 6, 7, 8}
    assert session_probe.STATE_ENABLED == 1


def test_stop_ends_every_child_and_kills_what_does_not_end(session):
    quiet, stubborn, gone = _Proc(), _Proc(wait_raises=True), _Proc(code=0)
    session.children = [quiet, stubborn, gone]
    session.stop()
    assert quiet.events == ["terminate"] and gone.events == []
    assert stubborn.events == ["terminate", "kill"]


def test_the_environment_of_the_session_has_no_x11_and_no_language(session, monkeypatch):
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setenv("LANGUAGE", "hu")
    monkeypatch.setenv("LC_ALL", "hu_HU.UTF-8")
    session.session_bus, session.system_bus = "unix:path=/a", "unix:path=/b"
    env = session.env()
    assert "DISPLAY" not in env and "LANGUAGE" not in env and "LC_ALL" not in env
    assert (
        env["LANG"] == "C"
        and env["WAYLAND_DISPLAY"] == "wl-gate"
        and env["GDK_BACKEND"] == "wayland"
    )
    assert env["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/a"
    assert env["DBUS_SYSTEM_BUS_ADDRESS"] == "unix:path=/b"
    assert env["HOME"] == session.home and env["XDG_RUNTIME_DIR"] == session.run_dir


def test_the_logs_are_printed_after_a_failure_with_their_last_lines(session, capsys):
    _write(session.shell_log, "\n".join(f"shell {n}" for n in range(100)))
    _write(session.program_log, "program line")
    session.print_logs()
    out = capsys.readouterr().out
    assert "shell 99" in out and "shell 60" in out and "shell 59" not in out
    assert "program line" in out and "log of gnome-shell" in out


def _bus_box(session, session_probe, monkeypatch, tmp_path, services):
    """``start_bus`` with a directory of service files of its own and no real bus: the stand-in for
    ``spawn`` makes the socket that the bus would make."""
    source = tmp_path / "dbus-services"
    source.mkdir()
    for name in services:
        (source / name).write_text(f"[D-BUS Service]\nName={name}\n", encoding="utf-8")
    monkeypatch.setattr(session_probe, "SERVICE_DIR", str(source))
    monkeypatch.setattr(session_probe.time, "sleep", lambda seconds: None)
    spawned = []

    def spawn(command, log, **kwargs):
        config = [part for part in command if part.startswith("--config-file=")][0]
        text = Path(config.split("=", 1)[1]).read_text(encoding="utf-8")
        socket_path = text.split("<listen>unix:path=")[1].split("</listen>")[0]
        Path(socket_path).touch()
        spawned.append((command, text, kwargs.get("env")))
        return _Proc()

    session.spawn = spawn
    Path(session.run_dir).mkdir(parents=True, exist_ok=True)
    Path(session.tmp).mkdir(parents=True, exist_ok=True)
    return spawned


def test_the_session_bus_can_start_the_dconf_and_the_extension_service_only(
    session, session_probe, monkeypatch, tmp_path
):
    every = ["ca.desrt.dconf.service", "org.gnome.Shell.Extensions.service", "org.other.service"]
    spawned = _bus_box(session, session_probe, monkeypatch, tmp_path, every)
    address = session.start_bus("session", services=True)
    command, text, env = spawned[0]
    assert address == f"unix:path={session.run_dir}/session.sock"
    service_dir = Path(session.tmp) / "services"
    assert sorted(p.name for p in service_dir.iterdir()) == every[:2]
    assert f"<servicedir>{service_dir}</servicedir>" in text
    assert command[:2] == ["dbus-daemon", "--nofork"]
    # what the bus starts has the environment of the session (HOME, XDG_RUNTIME_DIR), none empty
    assert env["HOME"] == session.home and env["XDG_RUNTIME_DIR"] == session.run_dir
    assert all(env.values())


def test_the_system_bus_starts_nothing(session, session_probe, monkeypatch, tmp_path):
    spawned = _bus_box(session, session_probe, monkeypatch, tmp_path, ["ca.desrt.dconf.service"])
    session.start_bus("system", services=False)
    assert "servicedir" not in spawned[0][1]
    assert not (Path(session.tmp) / "services").exists()


def test_a_bus_cannot_start_a_service_that_is_not_installed(
    session, session_probe, monkeypatch, tmp_path
):
    _bus_box(session, session_probe, monkeypatch, tmp_path, ["ca.desrt.dconf.service"])
    with pytest.raises(session_probe.Failed, match="org.gnome.Shell.Extensions.service is not"):
        session.start_bus("session", services=True)


def test_a_bus_that_does_not_come_up_is_a_failure(session, session_probe, monkeypatch, tmp_path):
    _bus_box(session, session_probe, monkeypatch, tmp_path, [])
    session.spawn = lambda command, log, **kwargs: _Proc()
    with pytest.raises(session_probe.Failed, match="the session bus did not come up"):
        session.start_bus("session", services=False)


# ---- the inside of the probes: the decisions that no step test reached ---------------------------
# Found by an automatic sweep of the probes (every condition taken away, every comparison turned
# round, every raise left out): these are the survivors of the first sweep, each with the test that
# kills it.


@pytest.mark.parametrize(
    "script, args, status, text",
    [
        ("probe_installed.py", [], 2, "usage"),  # it wants the version of the RPM
        ("probe_session.py", ["--help"], 0, "usage:"),
    ],
)
def test_the_scripts_run_their_main_when_they_are_started_as_scripts(script, args, status, text):
    """check.sh starts them with ``python3 -I script``. A script whose ``__main__`` guard never
    holds would end with 0 and say nothing: the gate would pass with no probe run."""
    result = subprocess.run(
        [sys.executable, "-I", str(GATE / script), *args],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env={"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == status, (result.stdout, result.stderr)
    assert text in result.stdout + result.stderr


def test_the_environment_of_a_command_has_no_language_but_the_rest_stays(
    installed, monkeypatch, tmp_path
):
    for name, value in (("LANGUAGE", "hu"), ("LC_ALL", "hu_HU.UTF-8"), ("LC_MESSAGES", "hu")):
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("PATH", "/x/bin")
    monkeypatch.setenv("HOME", "/root")
    env = installed._clean_env(str(tmp_path))
    assert not {"LANGUAGE", "LC_ALL", "LC_MESSAGES"} & set(env)
    assert env["PATH"] == "/x/bin"
    assert env["LANG"] == "C" and env["HOME"] == str(tmp_path)
    assert env["XDG_RUNTIME_DIR"] == str(tmp_path / "run") and (tmp_path / "run").is_dir()


def test_tools_say_what_is_wrong_with_the_encoders_in_the_message(installed, monkeypatch):
    _Programs(monkeypatch, installed, encoders="aac\n", encoders_rc=0)
    with pytest.raises(AssertionError, match="libmp3lame missing"):
        installed.step_tools()
    _Programs(monkeypatch, installed, encoders="libmp3lame\n", encoders_rc=1)
    with pytest.raises(AssertionError, match="libmp3lame present"):
        installed.step_tools()


def test_shell_waits_until_the_fake_desktop_says_it_is_up(session, session_probe, monkeypatch):
    """The first thing the step waits for is the line of the fake desktop in its log, not its
    absence."""
    waits = []
    session.start_bus = lambda name, services: f"unix:path=/{name}"
    session.spawn = lambda command, log, **kwargs: _Proc()

    def wait_for(what, check, timeout=None):
        waits.append((what, check))
        return "49.10" if len(waits) == 2 else True

    session.wait_for = wait_for
    session.step_shell()
    what, check = waits[0]
    assert "fake desktop" in what
    fake_log = os.path.join(session.tmp, "fake-desktop.log")
    assert not check()  # no log yet
    _write(fake_log, "starting\n")
    assert not check()
    _write(fake_log, "starting\nfake-desktop up\n")
    assert check()


@pytest.mark.parametrize(
    "code, out, answer",
    [
        (0, "(<'49.10'>,)", "49.10"),
        (1, "(<'49.10'>,)", ""),  # a call that failed is no answer, whatever it printed
        (0, "()", ""),
        (0, "", ""),
    ],
)
def test_shell_takes_the_version_only_from_an_answer_that_succeeded(
    session, session_probe, monkeypatch, code, out, answer
):
    waits = []
    session.start_bus = lambda name, services: f"unix:path=/{name}"
    session.spawn = lambda command, log, **kwargs: _Proc()
    session.wait_for = lambda what, check, timeout=None: waits.append(check) or True
    session.gdbus = lambda *args: _done(code, out)
    session.step_shell()
    assert waits[1]() == answer


def test_the_program_has_ended_only_when_there_is_one_and_it_has_exited(session):
    assert not session._program_ended()  # none started
    session.program = _Proc()
    assert not session._program_ended()  # running
    session.program = _Proc(code=3)
    assert session._program_ended()


def test_a_call_to_the_dot_sends_the_arguments_it_is_given_and_none_for_no_arguments(session):
    pytest.importorskip("gi")
    from gi.repository import GLib

    sent = []
    conn = type("Conn", (), {"call_sync": lambda self, *a: sent.append(a) or "reply"})()
    session.item = ":1.5/org/ayatana/NotificationItem/x"
    assert session._call(conn, "/p", "iface", "Method", ("hello",), "(s)") == "reply"
    assert session._call(conn, "/p", "iface", "Other", None, "()") == "reply"
    with_args, without = sent
    assert with_args[:4] == (":1.5", "/p", "iface", "Method")
    assert with_args[4].equal(GLib.Variant("(s)", ("hello",)))
    assert without[:4] == (":1.5", "/p", "iface", "Other") and without[4] is None
