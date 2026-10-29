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
    replaced = []
    add_calls = 0
    add_error = None
    add_result = ["region-video-audio", "region-video"]
    skipped = []

    def __init__(self, command, **_kw):
        FakeShortcuts.made.append(command)

    def add_missing(self):
        FakeShortcuts.add_calls += 1
        if FakeShortcuts.add_error:
            raise sc.ShortcutError(FakeShortcuts.add_error)
        return FakeShortcuts.add_result

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
    FakeShortcuts.add_calls, FakeShortcuts.add_error, FakeShortcuts.skipped = 0, None, []
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


def test_shortcuts_install_says_which_prototype_keys_it_replaced(shortcuts, capsys):
    shortcuts.replaced = ["felvetel.sh kep"]
    assert cli.main(["shortcuts", "install"]) == 0
    assert "replaced the old key that ran: felvetel.sh kep" in capsys.readouterr().out
    shortcuts.replaced = []


class Dot:
    """What ``indicator.run`` is called with by the autostart command."""

    calls = []


@pytest.fixture
def dot(monkeypatch):
    from hotrec import indicator

    Dot.calls = []
    monkeypatch.setattr(
        indicator, "run", lambda recorder, resident=False: Dot.calls.append(resident) or 0
    )
    return Dot


def test_autostart_sets_the_shortcuts_the_first_time_and_keeps_the_dot(shortcuts, dot):
    marker = sc.done_marker()
    assert not marker.exists()
    assert cli.main(["autostart"]) == 0
    assert shortcuts.made == ["/usr/bin/hotrec"]
    assert FakeRecorder.notes[0][0] == "Keyboard shortcuts are set"
    assert marker.read_text(encoding="utf-8") == __version__ + "\n"
    assert dot.calls == [True]  # the resident dot


def test_autostart_does_not_set_them_again(shortcuts, dot):
    cli.main(["autostart"])
    shortcuts.made.clear()
    FakeRecorder.notes.clear()
    assert cli.main(["autostart"]) == 0
    assert shortcuts.made == [] and FakeRecorder.notes == []
    assert dot.calls == [True, True]


def test_autostart_with_a_key_taken_tells_once_and_still_starts_the_dot(
    shortcuts, dot, monkeypatch
):
    class Taken(FakeShortcuts):
        def install(self):
            raise sc.ShortcutConflict("already used")

    monkeypatch.setattr(cli, "Shortcuts", Taken)
    assert cli.main(["autostart"]) == 0
    assert FakeRecorder.notes == [("Could not set the keyboard shortcuts", "already used")]
    assert sc.done_marker().exists()  # a person has to decide: no nagging at every login
    FakeRecorder.notes.clear()
    cli.main(["autostart"])
    assert FakeRecorder.notes == [] and dot.calls == [True, True]


def test_autostart_tries_again_at_the_next_login_after_another_failure(shortcuts, dot):
    shortcuts.error = "gsettings not found"
    assert cli.main(["autostart"]) == 0
    assert FakeRecorder.notes == [("Could not set the keyboard shortcuts", "gsettings not found")]
    assert not sc.done_marker().exists()
    assert dot.calls == [True]  # the dot does not wait for the shortcuts
    shortcuts.error = None
    cli.main(["autostart"])
    assert sc.done_marker().exists()


def test_autostart_works_when_the_marker_cannot_be_written(shortcuts, dot, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", "/proc/hotrec-test-no-such-place")
    assert cli.main(["autostart"]) == 0
    assert dot.calls == [True]


def regions_marker():
    return sc.done_marker().with_name("shortcuts-regions-added")


def test_autostart_adds_the_two_area_keys_for_a_person_who_has_the_old_ones(shortcuts, dot):
    marker = sc.done_marker()
    marker.parent.mkdir(parents=True)
    marker.write_text("0.1.4\n", encoding="utf-8")  # the four keys were set by 0.1.4
    assert cli.main(["autostart"]) == 0
    assert shortcuts.made == ["/usr/bin/hotrec"]  # only to add the missing: no full install
    assert shortcuts.add_calls == 1
    assert FakeRecorder.notes == []  # no manual step, no notification
    assert regions_marker().exists()
    assert marker.read_text(encoding="utf-8") == "0.1.4\n"  # the old marker is left as it was
    cli.main(["autostart"])
    assert shortcuts.add_calls == 1  # once, not at every login


def test_autostart_first_install_also_settles_the_area_keys(shortcuts, dot):
    cli.main(["autostart"])
    assert regions_marker().exists()


def test_autostart_tries_the_area_keys_again_when_gsettings_fails(shortcuts, dot):
    sc.done_marker().parent.mkdir(parents=True)
    sc.done_marker().write_text("0.1.4\n", encoding="utf-8")
    shortcuts.add_error = "gsettings not found"
    assert cli.main(["autostart"]) == 0
    assert dot.calls == [True]  # the dot does not wait for them
    assert not regions_marker().exists()
    shortcuts.add_error = None
    cli.main(["autostart"])
    assert regions_marker().exists() and shortcuts.add_calls == 2


def test_autostart_a_taken_area_key_is_logged_not_notified_and_settled(shortcuts, dot, caplog):
    sc.done_marker().parent.mkdir(parents=True)
    sc.done_marker().write_text("0.1.4\n", encoding="utf-8")
    shortcuts.add_result = []
    shortcuts.skipped = [("region-video", "/custom7/")]
    with caplog.at_level("WARNING"):
        cli.main(["autostart"])
    assert "region-video not added" in caplog.text and "/custom7/" in caplog.text
    assert FakeRecorder.notes == [] and regions_marker().exists()
    shortcuts.add_result = ["region-video-audio", "region-video"]


def test_select_region_runs_the_area_window(monkeypatch):
    from hotrec import selector

    monkeypatch.setattr(selector, "run", lambda: 3)
    assert cli.main(["select-region"]) == 3


def test_indicator_runs_the_dot(monkeypatch):
    from hotrec import indicator

    seen = []
    monkeypatch.setattr(indicator, "run", lambda recorder: seen.append(recorder) or 0)
    assert cli.main(["indicator"]) == 0
    assert len(seen) == 1
