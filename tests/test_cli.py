# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest

from hotrec import __version__, cli
from hotrec import recorder as rec
from hotrec import shortcuts as sc


class FakeRecorder:
    calls = []
    state = None
    notes = []

    def toggle(self, mode):
        FakeRecorder.calls.append(("toggle", mode))
        return 0

    def pause(self):
        FakeRecorder.calls.append(("pause",))
        return 0

    def stop(self):
        FakeRecorder.calls.append(("stop",))
        return 0

    def status(self):
        return FakeRecorder.state

    def notify(self, summary, body=""):
        FakeRecorder.notes.append((summary, body))


@pytest.fixture(autouse=True)
def fake(monkeypatch, env):
    FakeRecorder.calls, FakeRecorder.state, FakeRecorder.notes = [], None, []
    monkeypatch.setattr(cli, "Recorder", FakeRecorder)


@pytest.mark.parametrize("mode", rec.MODES)
def test_a_mode_toggles(mode):
    assert cli.main([mode]) == 0
    assert FakeRecorder.calls == [("toggle", mode)]


def test_pause_and_stop():
    assert cli.main(["pause"]) == 0 and cli.main(["stop"]) == 0
    assert FakeRecorder.calls == [("pause",), ("stop",)]


def test_status_idle(capsys):
    assert cli.main(["status"]) == 1
    assert capsys.readouterr().out == "not recording\n"


def test_status_recording_and_paused(capsys):
    FakeRecorder.state = rec.State(1, 2, "audio", "/f/x.mp3")
    assert cli.main(["status"]) == 0
    assert capsys.readouterr().out == "audio /f/x.mp3\n"
    FakeRecorder.state.paused = True
    cli.main(["status"])
    assert capsys.readouterr().out == "audio /f/x.mp3 (paused)\n"


def test_version(capsys):
    with pytest.raises(SystemExit) as stop:
        cli.main(["--version"])
    assert stop.value.code == 0
    assert capsys.readouterr().out == "hotrec %s\n" % __version__


@pytest.mark.parametrize(
    "argv", [[], ["cpu"], ["shortcuts"], ["shortcuts", "explode"], ["--encoder", "cpu"]]
)
def test_bad_command_lines_are_refused(argv):
    with pytest.raises(SystemExit) as stop:
        cli.main(argv)
    assert stop.value.code == 2


def test_the_help_has_no_cpu_mode(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    out = capsys.readouterr().out
    assert "cpu" not in out.lower() and "x264" not in out


class FakeShortcuts:
    made = []
    error = None

    def __init__(self, command, **_kw):
        FakeShortcuts.made.append(command)

    def install(self):
        if FakeShortcuts.error:
            raise sc.ShortcutError(FakeShortcuts.error)
        return ["line 1", "line 2"]

    def remove(self):
        return ["a", "b"]

    def status(self):
        return [(sc.SHORTCUTS[0], "hotrec video-audio"), (sc.SHORTCUTS[1], None)]


@pytest.fixture
def shortcuts(monkeypatch):
    FakeShortcuts.made, FakeShortcuts.error = [], None
    monkeypatch.setattr(cli, "Shortcuts", FakeShortcuts)
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/hotrec")
    return FakeShortcuts


def test_shortcuts_install_prints_the_lines_and_uses_the_path_hotrec(shortcuts, capsys):
    assert cli.main(["shortcuts", "install"]) == 0
    assert capsys.readouterr().out == "line 1\nline 2\n"
    assert shortcuts.made == ["/usr/bin/hotrec"]


def test_shortcuts_install_with_an_explicit_command(shortcuts):
    cli.main(["shortcuts", "install", "--command", "/home/me/hotrec/run.sh"])
    assert shortcuts.made == ["/home/me/hotrec/run.sh"]


def test_shortcuts_install_without_hotrec_on_the_path_says_what_to_do(
    shortcuts, monkeypatch, capsys
):
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    assert cli.main(["shortcuts", "install"]) == 1
    assert "--command" in capsys.readouterr().err


def test_shortcuts_remove_and_status(shortcuts, capsys, monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)  # not needed for these two
    assert cli.main(["shortcuts", "remove"]) == 0
    assert cli.main(["shortcuts", "status"]) == 0
    out = capsys.readouterr().out
    assert "removed 2 shortcuts" in out and "not set" in out and "hotrec video-audio" in out


def test_shortcuts_failure_is_status_1_with_the_reason(shortcuts, capsys):
    shortcuts.error = "already used"
    assert cli.main(["shortcuts", "install"]) == 1
    assert "already used" in capsys.readouterr().err


def test_setup_says_so_in_a_notification(shortcuts):
    assert cli.main(["setup"]) == 0
    summary, body = FakeRecorder.notes[0]
    assert summary == "Keyboard shortcuts are set"
    for key in ("F9", "F10", "F11", "F12"):
        assert key in body


def test_setup_failure_is_a_notification_too(shortcuts):
    shortcuts.error = "gsettings not found"
    assert cli.main(["setup"]) == 1
    assert FakeRecorder.notes == [("Could not set the keyboard shortcuts", "gsettings not found")]


def test_indicator_runs_the_dot(monkeypatch):
    from hotrec import indicator

    seen = []
    monkeypatch.setattr(indicator, "run", lambda recorder: seen.append(recorder) or 0)
    assert cli.main(["indicator"]) == 0
    assert len(seen) == 1
