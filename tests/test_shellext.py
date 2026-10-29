# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path

import pytest

from hotrec import __version__, cli, shellext
from hotrec import shortcuts as sc


class Gsettings:
    """Answers ``gsettings get|set`` for the two keys of org.gnome.shell."""

    def __init__(
        self, enabled="@as []", disabled="@as []", fail_set=False, fail_get=None, shell=None
    ):
        # ``shell``: what the running Shell answers to GetExtensionInfo (None: it is not asked)
        self.shell = shell
        self.asked = []
        self.values = {"enabled-extensions": enabled, "disabled-extensions": disabled}
        self.fail_set = fail_set
        self.fail_get = fail_get
        self.calls = []

    def __call__(self, args):
        if args[0] == "gdbus":
            self.asked.append(list(args))
            if self.shell is None:
                return 1, "no session bus"
            return 0, self.shell + "\n"
        self.calls.append(list(args))
        assert args[0] == "gsettings" and args[2] == "org.gnome.shell"
        if args[1] == "get":
            if self.fail_get == args[3]:
                return 1, "no such key"
            return 0, self.values[args[3]] + "\n"
        assert args[1] == "set"
        if self.fail_set:
            return 1, "denied"
        self.values[args[3]] = args[4]
        return 0, ""

    def sets(self):
        return [c for c in self.calls if c[1] == "set"]


@pytest.fixture
def package(env):
    """The extension package is installed: its metadata.json is in a system data directory."""
    folder = Path(env["XDG_DATA_DIRS"]) / "gnome-shell" / "extensions" / shellext.UUID
    folder.mkdir(parents=True)
    (folder / "metadata.json").write_text("{}", encoding="utf-8")
    return folder


class Notes:
    def __init__(self):
        self.notes = []

    def __call__(self, summary, body=""):
        self.notes.append((summary, body))


def offer(gs, notes, which=lambda name: "/usr/bin/" + name):
    return shellext.offer(notes, run=gs, which=which)


def test_the_uuid_is_the_one_of_the_extension_in_the_repository():
    import json

    root = Path(__file__).resolve().parent.parent / "gnome-shell"
    folder = root / shellext.UUID
    assert (
        json.loads((folder / "metadata.json").read_text(encoding="utf-8"))["uuid"] == shellext.UUID
    )
    assert [p.name for p in root.iterdir()] == [shellext.UUID]


def test_it_is_found_in_the_system_and_in_the_users_data_directory(env, package):
    assert shellext.installed()
    package.joinpath("metadata.json").unlink()
    assert not shellext.installed()
    own = Path(env["XDG_DATA_HOME"]) / "gnome-shell" / "extensions" / shellext.UUID
    own.mkdir(parents=True)
    (own / "metadata.json").write_text("{}", encoding="utf-8")
    assert shellext.installed()


def test_a_directory_without_metadata_is_no_extension(env):
    folder = Path(env["XDG_DATA_DIRS"]) / "gnome-shell" / "extensions" / shellext.UUID
    folder.mkdir(parents=True)
    assert not shellext.installed()


def test_the_default_data_directories_are_searched_when_the_variables_are_not_set():
    found = shellext.extension_dirs({"HOME": "/home/x"})
    assert found == [
        Path("/home/x/.local/share/gnome-shell/extensions") / shellext.UUID,
        Path("/usr/local/share/gnome-shell/extensions") / shellext.UUID,
        Path("/usr/share/gnome-shell/extensions") / shellext.UUID,
    ]


def test_the_first_time_it_is_enabled_and_the_user_is_told(package):
    gs, notes = Gsettings(enabled="['appindicatorsupport@rgcjonas.gmail.com']"), Notes()
    assert offer(gs, notes) is True
    assert gs.sets() == [
        [
            "gsettings",
            "set",
            "org.gnome.shell",
            "enabled-extensions",
            "['appindicatorsupport@rgcjonas.gmail.com', 'hotrec-dot@trensoft.github.io']",
        ]
    ]
    assert len(notes.notes) == 1
    summary, body = notes.notes[0]
    assert summary == "Hotrec"
    assert "log out and in" in body and "Extensions app" in body
    assert shellext.offered_marker().read_text(encoding="utf-8") == __version__ + "\n"


def info(state, uuid=shellext.UUID):
    """What gdbus prints for GetExtensionInfo of an extension the Shell has loaded."""
    return "({'uuid': <'%s'>, 'name': <'Hotrec'>, 'state': <%s>},)" % (uuid, state)


NOT_KNOWN = "(@a{sv} {},)"  # as gdbus prints an empty dictionary


def test_when_the_shell_knows_the_extension_the_user_is_not_asked_to_log_out(package):
    gs, notes = Gsettings(shell=info("2.0")), Notes()
    assert offer(gs, notes) is True
    assert len(gs.sets()) == 1
    ((summary, body),) = notes.notes
    assert summary == "Hotrec"
    assert "log out" not in body and "Extensions app" in body
    assert body.startswith("The blinking red dot over a fullscreen video is on.")
    assert shellext.offered_marker().exists()
    assert gs.asked == [
        [
            "gdbus", "call", "--session",
            "--dest", "org.gnome.Shell.Extensions",
            "--object-path", "/org/gnome/Shell/Extensions",
            "--method", "org.gnome.Shell.Extensions.GetExtensionInfo",
            "hotrec-dot@trensoft.github.io",
        ]
    ]  # fmt: skip


@pytest.mark.parametrize(
    "answer",
    [
        NOT_KNOWN,  # the package came after the login: the Shell has never seen it
        None,  # the Shell cannot be asked
        info("3.0"),  # ERROR
        info("4.0"),  # OUT_OF_DATE
        info("99.0"),  # UNINSTALLED
        "({'uuid': <'hotrec-dot@trensoft.github.io'>},)",  # no state to read
        info("2.0", uuid="other@example.org"),  # somebody else's extension
    ],
)
def test_in_every_other_case_the_user_is_asked_to_log_out(package, answer):
    gs, notes = Gsettings(shell=answer), Notes()
    assert offer(gs, notes) is True
    assert len(gs.sets()) == 1  # it is still switched on, only the words differ
    assert "log out and in" in notes.notes[0][1]


@pytest.mark.parametrize("state", ["1.0", "2.0", "6.0", "7.0", "8.0", "double 2.0", "uint32 2"])
def test_a_loaded_extension_in_any_working_state_counts_as_known(package, state):
    gs, notes = Gsettings(shell=info(state)), Notes()
    offer(gs, notes)
    assert "log out" not in notes.notes[0][1]


def test_without_gdbus_the_shell_is_not_asked(package):
    gs, notes = Gsettings(shell=info("2.0")), Notes()
    shellext.offer(
        notes, run=gs, which=lambda name: None if name == "gdbus" else "/usr/bin/" + name
    )
    assert gs.asked == [] and "log out and in" in notes.notes[0][1]


def test_an_answer_of_a_failed_call_is_not_believed():
    assert (
        shellext.shell_knows(lambda args: (1, info("2.0")), lambda name: "/usr/bin/gdbus") is False
    )
    assert (
        shellext.shell_knows(lambda args: (0, info("2.0")), lambda name: "/usr/bin/gdbus") is True
    )


def test_the_shell_is_asked_before_the_setting_is_changed(package):
    order = []
    gs = Gsettings(shell=info("2.0"))

    def run(args):
        order.append(args[1] if args[0] == "gsettings" else "gdbus")
        return gs(args)

    shellext.offer(Notes(), run=run, which=lambda name: "/usr/bin/" + name)
    assert order == ["get", "get", "gdbus", "set"]


def test_an_empty_list_gets_just_ours(package):
    gs = Gsettings(enabled="@as []")
    offer(gs, Notes())
    assert gs.values["enabled-extensions"] == "['hotrec-dot@trensoft.github.io']"


def test_it_is_offered_once_only(package):
    gs, notes = Gsettings(), Notes()
    assert offer(gs, notes) is True
    gs.values["enabled-extensions"] = "@as []"  # the user turned it off in the Extensions app
    gs.calls.clear()
    assert offer(gs, notes) is False
    assert gs.calls == [] and len(notes.notes) == 1


def test_removing_the_marker_offers_it_again(package):
    gs, notes = Gsettings(), Notes()
    offer(gs, notes)
    shellext.offered_marker().unlink()
    gs.values["enabled-extensions"] = "@as []"
    assert offer(gs, notes) is True


def test_nothing_happens_when_the_package_is_not_installed(env):
    gs, notes = Gsettings(), Notes()
    assert offer(gs, notes) is False
    assert gs.calls == [] and notes.notes == []
    assert not shellext.offered_marker().exists()  # it may be installed later


def test_nothing_happens_without_gsettings(package):
    gs, notes = Gsettings(), Notes()
    assert offer(gs, notes, which=lambda name: None) is False
    assert gs.calls == [] and notes.notes == [] and not shellext.offered_marker().exists()


def test_already_enabled_counts_as_offered_without_a_notification(package):
    gs, notes = Gsettings(enabled="['hotrec-dot@trensoft.github.io']"), Notes()
    assert offer(gs, notes) is False
    assert gs.sets() == [] and notes.notes == []
    assert shellext.offered_marker().exists()


def test_an_extension_the_user_disabled_on_purpose_is_left_alone(package):
    gs, notes = Gsettings(disabled="['hotrec-dot@trensoft.github.io']"), Notes()
    assert offer(gs, notes) is False
    assert gs.sets() == [] and notes.notes == []
    assert shellext.offered_marker().exists()


@pytest.mark.parametrize("key", ["enabled-extensions", "disabled-extensions"])
def test_a_key_that_cannot_be_read_is_tried_again_at_the_next_login(package, key):
    gs, notes = Gsettings(fail_get=key), Notes()
    assert offer(gs, notes) is False
    assert gs.sets() == [] and notes.notes == [] and not shellext.offered_marker().exists()


def test_a_list_that_is_no_list_is_not_overwritten(package):
    gs, notes = Gsettings(enabled="nonsense"), Notes()
    assert offer(gs, notes) is False
    assert gs.sets() == [] and notes.notes == [] and not shellext.offered_marker().exists()


def test_a_failed_write_says_nothing_and_is_tried_again(package):
    gs, notes = Gsettings(fail_set=True), Notes()
    assert offer(gs, notes) is False
    assert notes.notes == [] and not shellext.offered_marker().exists()


def test_a_marker_that_cannot_be_written_does_not_stop_it(package, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", "/proc/hotrec-test-no-such-place")
    gs, notes = Gsettings(), Notes()
    assert offer(gs, notes) is True
    assert len(notes.notes) == 1


def test_the_marker_is_next_to_the_one_of_the_shortcuts(env):
    assert shellext.offered_marker().parent == sc.done_marker().parent
    assert shellext.offered_marker() != sc.done_marker()


# -- the login command ---------------------------------------------------------------------


class Recorder:
    def notify(self, summary, body=""):
        pass

    def status(self):
        return None


def test_autostart_offers_the_extension_before_the_dot_and_passes_the_notification(
    env, monkeypatch
):
    from hotrec import indicator

    order = []
    recorder = Recorder()
    monkeypatch.setattr(cli, "Recorder", lambda: recorder)
    monkeypatch.setattr(cli, "_set_shortcuts", lambda r: None)
    monkeypatch.setattr(cli.shellext, "offer", lambda notify: order.append(("offer", notify)))
    monkeypatch.setattr(
        indicator, "run", lambda r, resident=False: order.append(("dot", resident)) or 0
    )
    assert cli.main(["autostart"]) == 0
    assert order == [("offer", recorder.notify), ("dot", True)]


def test_a_broken_offer_does_not_keep_the_dot_from_starting(env, monkeypatch):
    # offer() answers its own failures; this is the line of defence for the one it did not think of
    from hotrec import indicator

    started = []
    monkeypatch.setattr(cli, "Recorder", Recorder)
    monkeypatch.setattr(cli, "_set_shortcuts", lambda r: None)

    def broken(notify):
        raise RuntimeError("boom")

    monkeypatch.setattr(cli.shellext, "offer", broken)
    monkeypatch.setattr(indicator, "run", lambda r, resident=False: started.append(1) or 0)
    assert cli.main(["autostart"]) == 0
    assert started == [1]
