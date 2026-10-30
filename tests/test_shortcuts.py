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


def test_the_six_shortcuts_are_f9_to_f12_then_the_two_area_keys_f7_and_f8():
    assert [(s.slug, s.accelerator, s.keys) for s in sc.SHORTCUTS] == [
        ("video-audio", "<Primary><Shift>F9", "Ctrl+Shift+F9"),
        ("video", "<Primary><Shift>F10", "Ctrl+Shift+F10"),
        ("audio", "<Primary><Shift>F11", "Ctrl+Shift+F11"),
        ("pause", "<Primary><Shift>F12", "Ctrl+Shift+F12"),
        ("region-video-audio", "<Primary><Shift>F7", "Ctrl+Shift+F7"),
        ("region-video", "<Primary><Shift>F8", "Ctrl+Shift+F8"),
    ]


def test_paths_are_ours():
    paths = [sc.path_of(s) for s in sc.SHORTCUTS]
    assert (
        paths[0]
        == "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/hotrec-video-audio/"
    )
    assert len(set(paths)) == 6 and all(p.endswith("/") for p in paths)


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
    assert len(lines) == 6
    names = {p: v for (p, k), v in g.entries.items() if k == "name"}
    assert sorted(names.values()) == [
        "Pause or resume recording",
        "Record area and sound",
        "Record area only",
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
    assert len(sc.parse_list(g.listing)) == 7


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
    assert len(removed) == 6
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
    assert [run for _s, run in shortcuts.status()] == [None] * 6
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


# --- key combinations ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "canonical", "label"),
    [
        ("<Primary><Shift>F9", "<Primary><Shift>F9", "Ctrl+Shift+F9"),
        ("<Control><Shift>f10", "<Primary><Shift>F10", "Ctrl+Shift+F10"),
        ("<Shift><Ctrl>F11", "<Primary><Shift>F11", "Ctrl+Shift+F11"),
        ("<Mod1><Primary>R", "<Primary><Alt>r", "Ctrl+Alt+R"),
        ("<Mod4>space", "<Super>space", "Super+Space"),
        ("F8", "F8", "F8"),
        ("<Primary>Return", "<Primary>Return", "Ctrl+Return"),
    ],
)
def test_one_spelling_for_the_same_keys(text, canonical, label):
    assert sc.canonical_accelerator(text) == canonical
    assert sc.accelerator_label(text) == label


@pytest.mark.parametrize("text", ["", "   ", "disabled", "<Primary>", "<Primary> F9", "a b"])
def test_what_is_no_key_combination(text):
    assert sc.canonical_accelerator(text) is None
    assert sc.accelerator_problem(text) == "keys"
    assert sc.accelerator_label(text) == text


def test_same_accelerator_compares_keys_not_text():
    assert sc.same_accelerator("<Control><Shift>f9", "<Primary><Shift>F9")
    assert sc.same_accelerator("<Primary><Alt>R", "<Mod1><Control>r")
    assert not sc.same_accelerator("<Primary><Shift>F9", "<Primary>F9")
    assert not sc.same_accelerator("<Primary>F9", "<Primary>F10")
    assert not sc.same_accelerator("", "")
    assert not sc.same_accelerator("disabled", "disabled")


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("a", "modifier"),
        ("<Shift>a", "modifier"),
        ("<Shift>Tab", "modifier"),
        ("Escape", "modifier"),
        ("F1", None),
        ("<Shift>F5", None),
        ("<Primary>a", None),
        ("<Alt>Tab", None),
        ("<Super>space", None),
        ("<Primary><Shift>F9", None),
    ],
)
def test_a_letter_alone_is_no_shortcut(text, problem):
    assert sc.accelerator_problem(text) == problem


def test_bindings_are_what_gnome_has():
    g = Gsettings()
    shortcuts = make(g)
    assert shortcuts.bindings() == {s.slug: None for s in sc.SHORTCUTS}
    shortcuts.install({"audio": "<Primary><Alt>a"})
    assert shortcuts.bindings() == {
        "video-audio": "<Primary><Shift>F9",
        "video": "<Primary><Shift>F10",
        "audio": "<Primary><Alt>a",
        "pause": "<Primary><Shift>F12",
        "region-video-audio": "<Primary><Shift>F7",
        "region-video": "<Primary><Shift>F8",
    }


def test_bindings_without_gsettings_is_the_same_clear_error():
    shortcuts = sc.Shortcuts("hotrec", run=Gsettings(), which=lambda name: None)
    with pytest.raises(sc.ShortcutError):
        shortcuts.bindings()


def test_install_with_keys_changes_an_installed_shortcut_and_keeps_the_rest():
    g = Gsettings()
    shortcuts = make(g)
    shortcuts.install()
    lines = shortcuts.install({"video": "<Super>F2", "pause": "<Control><Alt>p"})
    assert lines == [
        "Ctrl+Shift+F9  hotrec video-audio",
        "Super+F2  hotrec video",
        "Ctrl+Shift+F11  hotrec audio",
        "Ctrl+Alt+P  hotrec pause",
        "Ctrl+Shift+F7  hotrec region-video-audio",
        "Ctrl+Shift+F8  hotrec region-video",
    ]
    assert g.entries[(sc.path_of(sc.SHORTCUTS[1]), "binding")] == "<Super>F2"
    assert g.entries[(sc.path_of(sc.SHORTCUTS[3]), "binding")] == "<Primary><Alt>p"
    assert len(sc.parse_list(g.listing)) == 6


def test_install_with_keys_that_are_no_keys_changes_nothing():
    g = Gsettings()
    with pytest.raises(sc.ShortcutError, match="not a key combination"):
        make(g).install({"video": "nonsense with spaces"})
    with pytest.raises(sc.ShortcutError, match="no shortcut called"):
        make(g).install({"nothing": "<Primary>F2"})
    assert g.calls == []


def test_install_refuses_two_shortcuts_on_the_same_keys_before_touching_gnome():
    g = Gsettings()
    with pytest.raises(sc.ShortcutError, match="same keys"):
        make(g).install({"video": "<Control><Shift>f9"})
    assert g.calls == []


def test_a_foreign_key_is_a_conflict_whatever_its_spelling():
    other = sc.PATH_PREFIX + "custom0/"
    for spelling in ("<Control><Shift>f9", "<Shift><Primary>F9", "<Primary><Shift>F9"):
        g = Gsettings("['%s']" % other, {(other, "binding"): spelling})
        with pytest.raises(sc.ShortcutConflict):
            make(g).install()
        assert not any(c[1] in ("set", "reset") for c in g.calls)


def test_a_foreign_key_on_a_key_we_leave_is_no_conflict():
    other = sc.PATH_PREFIX + "custom0/"
    g = Gsettings("['%s']" % other, {(other, "binding"): "<Primary><Shift>F9"})
    make(g).install({"video-audio": "<Primary><Shift>F2"})  # F9 is free once we do not take it
    assert g.entries[(sc.path_of(sc.SHORTCUTS[0]), "binding")] == "<Primary><Shift>F2"


# -- add_missing: the two area keys for a person who set the first four up with 0.1.4 -------------

OLD_FOUR = [s for s in sc.SHORTCUTS if not s.slug.startswith("region")]
NEW_TWO = [s for s in sc.SHORTCUTS if s.slug.startswith("region")]


def installed_by_the_old_version(extra=None, custom=None):
    """gsettings as 0.1.4 left it: the four entries (and a foreign one), keys as in ``custom``."""
    entries = {(OTHER, "binding"): "<Super>t"}
    paths = [OTHER]
    for s in OLD_FOUR:
        path = sc.path_of(s)
        paths.append(path)
        entries[(path, "name")] = "old name of " + s.slug
        entries[(path, "command")] = "hotrec " + s.slug
        entries[(path, "binding")] = (custom or {}).get(s.slug, s.accelerator)
    entries.update(extra or {})
    return Gsettings(repr(paths), entries)


def test_add_missing_adds_only_the_two_area_keys_and_touches_nothing_else():
    g = installed_by_the_old_version(custom={"video": "<Super>F2"})
    before = dict(g.entries)
    added = make(g, "/usr/bin/hotrec").add_missing()
    assert added == ["region-video-audio", "region-video"]
    for key, value in before.items():  # every value the person has is as it was
        assert g.entries[key] == value
    for s in NEW_TWO:
        assert g.entries[(sc.path_of(s), "binding")] == s.accelerator
        assert g.entries[(sc.path_of(s), "command")] == "/usr/bin/hotrec " + s.slug
    assert g.entries[(sc.path_of(NEW_TWO[0]), "name")] == "Record area and sound"
    assert g.entries[(sc.path_of(NEW_TWO[1]), "name")] == "Record area only"
    assert sc.parse_list(g.listing) == [OTHER] + [sc.path_of(s) for s in OLD_FOUR + NEW_TWO]
    assert not any(c[1] == "reset" for c in g.calls)


def test_add_missing_does_not_put_back_an_old_shortcut_a_person_took_out():
    # F9-F12 removed on purpose (``hotrec shortcuts remove``, or by hand): only the new ones come
    g = Gsettings(repr([OTHER]), {(OTHER, "binding"): "<Super>t"})
    shortcuts = make(g, "/usr/bin/hotrec")
    assert shortcuts.add_missing() == ["region-video-audio", "region-video"]
    listed = sc.parse_list(g.listing)
    assert listed == [OTHER] + [sc.path_of(s) for s in NEW_TWO]
    for s in OLD_FOUR:
        assert sc.path_of(s) not in listed
        assert not any(path == sc.path_of(s) for path, _ in g.entries)
    g.calls.clear()
    assert shortcuts.add_missing() == []  # and nothing more the second time
    assert not any(c[1] in ("set", "reset") for c in g.calls)


def test_add_missing_with_nothing_of_the_four_and_one_new_one_there_adds_the_other_new_one():
    g = Gsettings(repr([OTHER, sc.path_of(NEW_TWO[0])]), {(OTHER, "binding"): "<Super>t"})
    assert make(g).add_missing() == ["region-video"]
    assert not any(sc.path_of(s) in sc.parse_list(g.listing) for s in OLD_FOUR)


def test_add_missing_with_everything_there_changes_nothing():
    g = Gsettings()
    shortcuts = make(g)
    shortcuts.install()
    g.calls.clear()
    assert shortcuts.add_missing() == []
    assert not any(c[1] in ("set", "reset") for c in g.calls)


def test_add_missing_twice_changes_nothing_the_second_time():
    g = installed_by_the_old_version()
    shortcuts = make(g)
    shortcuts.add_missing()
    g.calls.clear()
    assert shortcuts.add_missing() == []
    assert not any(c[1] in ("set", "reset") for c in g.calls)


def test_add_missing_leaves_out_a_key_another_program_has_and_names_it():
    g = installed_by_the_old_version(
        extra={(OTHER, "binding"): "<Control><Shift>f8"}  # another program's, spelled differently
    )
    shortcuts = make(g)
    assert shortcuts.add_missing() == ["region-video-audio"]
    assert shortcuts.skipped == [("region-video", OTHER)]
    assert (sc.path_of(NEW_TWO[1]), "binding") not in g.entries
    assert sc.path_of(NEW_TWO[1]) not in sc.parse_list(g.listing)


def test_add_missing_leaves_out_a_key_the_person_gave_one_of_our_old_shortcuts():
    g = installed_by_the_old_version(custom={"pause": "<Primary><Shift>F7"})
    shortcuts = make(g)
    assert shortcuts.add_missing() == ["region-video"]
    assert shortcuts.skipped == [("region-video-audio", sc.path_of(OLD_FOUR[3]))]
    assert g.entries[(sc.path_of(OLD_FOUR[3]), "binding")] == "<Primary><Shift>F7"


def test_add_missing_with_a_failing_gsettings_is_a_shortcut_error():
    g = installed_by_the_old_version()
    g.fail_on = "set"
    with pytest.raises(sc.ShortcutError):
        make(g).add_missing()
    assert sc.path_of(NEW_TWO[0]) not in sc.parse_list(g.listing)  # not listed half done


def test_add_missing_without_gsettings_is_the_clear_error():
    shortcuts = sc.Shortcuts("hotrec", run=Gsettings(), which=lambda name: None)
    with pytest.raises(sc.ShortcutError):
        shortcuts.add_missing()
