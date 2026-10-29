# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

import ast

import pytest

from hotrec import shortcuts as sc

LIST = ("gsettings", "get", sc.SCHEMA, sc.LIST_KEY)
OTHER = sc.PATH_PREFIX + "custom0/"
EXISTING = "['%s']" % OTHER


class Gsettings:
    """A tiny gsettings: a list key and per-path entries, every call recorded."""

    def __init__(self, listing="@as []", entries=None, fail_on=None):
        self.listing = listing
        self.entries = dict(entries or {})  # (path, key) -> value
        self.calls = []
        self.fail_on = fail_on

    def __call__(self, args):
        args = list(args)
        self.calls.append(args)
        if self.fail_on and self.fail_on in " ".join(args):
            return 1, "boom"
        if args[:2] == ["gsettings", "get"] and args[2] == sc.SCHEMA:
            return 0, self.listing + "\n"
        if args[:2] == ["gsettings", "get"]:
            path = args[2].split(":", 1)[1]
            value = self.entries.get((path, args[3]))
            return (0, repr(value) + "\n") if value is not None else (1, "no such key")
        if args[:2] == ["gsettings", "set"] and args[2] == sc.SCHEMA:
            self.listing = args[4]
            return 0, ""
        if args[:2] == ["gsettings", "set"]:
            self.entries[(args[2].split(":", 1)[1], args[3])] = ast.literal_eval(args[4])
            return 0, ""
        if args[:2] == ["gsettings", "reset"]:
            self.entries.pop((args[2].split(":", 1)[1], args[3]), None)
            return 0, ""
        raise AssertionError(args)


def make(g, command="hotrec"):
    return sc.Shortcuts(command, run=g, which=lambda name: "/usr/bin/" + name)


def test_the_four_shortcuts_are_f9_to_f12_with_control_and_shift():
    assert [(s.slug, s.accelerator, s.keys) for s in sc.SHORTCUTS] == [
        ("video-audio", "<Primary><Shift>F9", "Ctrl+Shift+F9"),
        ("video", "<Primary><Shift>F10", "Ctrl+Shift+F10"),
        ("audio", "<Primary><Shift>F11", "Ctrl+Shift+F11"),
        ("pause", "<Primary><Shift>F12", "Ctrl+Shift+F12"),
    ]


def test_paths_are_ours():
    paths = [sc.path_of(s) for s in sc.SHORTCUTS]
    assert (
        paths[0]
        == "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/hotrec-video-audio/"
    )
    assert len(set(paths)) == 4 and all(p.endswith("/") for p in paths)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("@as []", []),
        ("[]", []),
        ("['/a/', '/b/']\n", ["/a/", "/b/"]),
        ('["/a/"]', ["/a/"]),
    ],
)
def test_parse_list(text, expected):
    assert sc.parse_list(text) == expected


@pytest.mark.parametrize(
    "text", ["", "nonsense", "5", "[1, 2]", "{'a': 1}", "@as [__import__('os')]"]
)
def test_parse_list_refuses_what_is_not_a_list_of_strings(text):
    with pytest.raises(sc.ShortcutError):
        sc.parse_list(text)


def test_gvariant_strings_are_escaped():
    assert sc.gvariant_string("a") == "'a'"
    assert sc.gvariant_string("it's") == "'it\\'s'"
    assert sc.gvariant_string("a\\b") == "'a\\\\b'"
    assert sc.gvariant_list([]) == "@as []"
    assert sc.gvariant_list(["/a/", "/b/"]) == "['/a/', '/b/']"


def test_install_on_an_empty_list():
    g = Gsettings()
    lines = make(g).install()
    assert lines[0] == "Ctrl+Shift+F9  hotrec video-audio"
    assert len(lines) == 4
    names = {p: v for (p, k), v in g.entries.items() if k == "name"}
    assert sorted(names.values()) == [
        "Pause or resume recording",
        "Record screen and sound",
        "Record screen only",
        "Record sound only",
    ]
    for s in sc.SHORTCUTS:
        assert g.entries[(sc.path_of(s), "binding")] == s.accelerator
        assert g.entries[(sc.path_of(s), "command")] == "hotrec " + s.slug
    assert sc.parse_list(g.listing) == [sc.path_of(s) for s in sc.SHORTCUTS]


def test_install_keeps_the_entries_of_other_programs():
    g = Gsettings(EXISTING, {(OTHER, "binding"): "<Super>t"})
    make(g).install()
    assert sc.parse_list(g.listing)[0] == OTHER
    assert len(sc.parse_list(g.listing)) == 5


def test_install_twice_changes_nothing_the_second_time():
    g = Gsettings()
    shortcuts = make(g)
    shortcuts.install()
    listing = g.listing
    g.calls.clear()
    shortcuts.install()
    assert g.listing == listing
    assert not any(c[:3] == ["gsettings", "set", sc.SCHEMA] for c in g.calls)


def test_install_refuses_a_key_another_entry_uses_and_changes_nothing():
    g = Gsettings(EXISTING, {(OTHER, "binding"): "<Primary><Shift>f9"})
    with pytest.raises(sc.ShortcutError) as caught:
        make(g).install()
    assert "Ctrl+Shift+F9" in str(caught.value) and OTHER in str(caught.value)
    assert not any(c[1] in ("set", "reset") for c in g.calls)


def test_our_own_old_entries_are_not_a_conflict():
    g = Gsettings()
    shortcuts = make(g)
    shortcuts.install()
    shortcuts.install()  # the binding is there already, it is ours


def test_the_command_is_quoted_for_the_desktop():
    g = Gsettings()
    make(g, "/opt/my apps/hotrec").install()
    assert (
        g.entries[(sc.path_of(sc.SHORTCUTS[0]), "command")] == "'/opt/my apps/hotrec' video-audio"
    )


def test_a_quote_in_the_command_survives_gvariant():
    assert sc.gvariant_string("it's") == "'it\\'s'"


def test_remove_takes_only_ours_and_resets_them():
    g = Gsettings(EXISTING, {(OTHER, "binding"): "<Super>t"})
    shortcuts = make(g)
    shortcuts.install()
    removed = shortcuts.remove()
    assert len(removed) == 4
    assert sc.parse_list(g.listing) == [OTHER]
    assert not [k for (p, k) in g.entries if p.startswith(sc.PATH_PREFIX + "hotrec")]
    assert g.entries[(OTHER, "binding")] == "<Super>t"


def test_remove_with_nothing_installed_does_nothing():
    g = Gsettings(EXISTING)
    assert make(g).remove() == []
    assert not any(c[1] in ("set", "reset") for c in g.calls)


def test_status():
    g = Gsettings()
    shortcuts = make(g)
    assert [run for _s, run in shortcuts.status()] == [None] * 4
    shortcuts.install()
    assert [run for _s, run in shortcuts.status()][3] == "hotrec pause"


def test_no_gsettings_is_a_clear_error():
    g = Gsettings()
    with pytest.raises(sc.ShortcutError, match="gsettings not found"):
        sc.Shortcuts("hotrec", run=g, which=lambda name: None).install()
    assert g.calls == []


def test_a_failing_gsettings_is_an_error_not_a_half_install():
    with pytest.raises(sc.ShortcutError, match="boom"):
        make(Gsettings(fail_on="get " + sc.SCHEMA)).install()


def test_a_failure_in_the_middle_surfaces():
    g = Gsettings(fail_on="binding")
    with pytest.raises(sc.ShortcutError):
        make(g).install()
    assert g.listing == "@as []"  # the list is written last: nothing is switched on half way


def test_the_real_runner_reports_a_missing_program_as_127():
    code, out = sc._run(["definitely-not-a-program-hotrec"])
    assert code == 127 and out


# -- the prototype's keys are replaced, nobody else's -------------------------------------------

LEGACY_COMMANDS = [
    "/home/attila/felvetel/felvetel.sh kepeshang",
    "felvetel.sh kep",
    "bash /opt/felvetel.sh hang",
    "'/home/a b/felvetel/felvetel.sh' szunet",
    "bash -c '~/felvetel/felvetel.sh kep'",
    "/usr/local/bin/felvetel kepeshang",
    "felvetel-kepeshang",
    "/home/attila/bin/felvetel-szunet",
]
FOREIGN_COMMANDS = [
    "",
    "hotrec video",
    "gnome-terminal",
    "/home/attila/felvetel/felvetel.sh",  # no mode
    "felvetel.sh kepek",  # not one of the four words
    "felvetel.sh kep2",
    "my-felvetel.sh kep",  # another script
    "/opt/felvetel/other kep",  # a directory of that name only
    "notfelvetel-kep",
    "felvetel-kepeshangx",
]


@pytest.mark.parametrize("command", LEGACY_COMMANDS)
def test_the_prototype_commands_are_recognised(command):
    assert sc.is_legacy_command(command)


@pytest.mark.parametrize("command", FOREIGN_COMMANDS)
def test_other_commands_are_not(command):
    assert not sc.is_legacy_command(command)


def old_key(n, command, binding="<Primary><Shift>F9", name="felvetel"):
    path = "%sfelvetel-%d/" % (sc.PATH_PREFIX, n)
    return path, {(path, "command"): command, (path, "binding"): binding, (path, "name"): name}


def old_setup():
    """Two of the prototype's keys (one on a key of ours, one on another), and a foreign one."""
    p1, e1 = old_key(1, "/home/attila/felvetel/felvetel.sh kepeshang", "<Primary><Shift>F9")
    p2, e2 = old_key(2, "/home/attila/felvetel/felvetel.sh szunet", "<Super>F12")
    entries = {(OTHER, "binding"): "<Super>t", (OTHER, "command"): "gnome-terminal"}
    entries.update(e1)
    entries.update(e2)
    listing = "['%s', '%s', '%s']" % (p1, OTHER, p2)
    return Gsettings(listing, entries), p1, p2


def test_install_replaces_the_prototype_keys_and_keeps_the_others():
    g, p1, p2 = old_setup()
    shortcuts = make(g)
    shortcuts.install()
    assert sc.parse_list(g.listing) == [OTHER] + [sc.path_of(s) for s in sc.SHORTCUTS]
    for path in (p1, p2):
        assert not [k for (p, k) in g.entries if p == path]  # name, command, binding reset
    assert g.entries[(OTHER, "binding")] == "<Super>t"
    assert g.entries[(OTHER, "command")] == "gnome-terminal"
    assert shortcuts.replaced == [
        "/home/attila/felvetel/felvetel.sh kepeshang",
        "/home/attila/felvetel/felvetel.sh szunet",
    ]
    for s in sc.SHORTCUTS:
        assert g.entries[(sc.path_of(s), "binding")] == s.accelerator


def test_the_prototype_key_on_one_of_our_keys_is_no_conflict():
    g, _p1, _p2 = old_setup()
    make(g).install()  # p1 holds Ctrl+Shift+F9; it is replaced, so the key is free


def test_a_second_install_replaces_nothing():
    g, _p1, _p2 = old_setup()
    shortcuts = make(g)
    shortcuts.install()
    listing = g.listing
    g.calls.clear()
    shortcuts.install()
    assert shortcuts.replaced == [] and g.listing == listing
    assert not any(c[1] in ("set", "reset") and "felvetel" in " ".join(c) for c in g.calls)


def test_a_foreign_key_with_a_prototype_name_is_not_touched():
    path = sc.PATH_PREFIX + "felvetel-kep/"
    entries = {
        (path, "command"): "/usr/bin/other-recorder kep",
        (path, "binding"): "<Super>F1",
        (path, "name"): "felvetel-kep",
    }
    g = Gsettings("['%s']" % path, entries)
    shortcuts = make(g)
    shortcuts.install()
    assert path in sc.parse_list(g.listing) and shortcuts.replaced == []
    assert entries.items() <= g.entries.items()


def test_a_foreign_key_on_our_key_is_still_a_conflict_next_to_a_prototype_key():
    g, _p1, _p2 = old_setup()
    g.entries[(OTHER, "binding")] = "<Primary><Shift>F10"
    with pytest.raises(sc.ShortcutConflict):
        make(g).install()
    assert not any(c[1] in ("set", "reset") for c in g.calls)  # the prototype keys stay too


def test_the_conflict_is_a_shortcut_error():
    assert issubclass(sc.ShortcutConflict, sc.ShortcutError)


def test_when_the_list_cannot_be_written_the_prototype_keys_stay():
    g, p1, p2 = old_setup()
    g.fail_on = "set %s %s" % (sc.SCHEMA, sc.LIST_KEY)
    with pytest.raises(sc.ShortcutError):
        make(g).install()
    assert (p1, "command") in g.entries and (p2, "binding") in g.entries
    assert not [c for c in g.calls if c[1] == "reset"]


def test_the_done_marker_is_under_the_state_home():
    assert str(sc.done_marker({"XDG_STATE_HOME": "/s", "HOME": "/h"})) == (
        "/s/hotrec/shortcuts-installed"
    )
    assert str(sc.done_marker({"HOME": "/h"})) == "/h/.local/state/hotrec/shortcuts-installed"
    assert str(sc.done_marker({"XDG_STATE_HOME": "rel", "HOME": "/h"})) == (
        "/h/.local/state/hotrec/shortcuts-installed"
    )
