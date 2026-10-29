# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

"""What a package needs from the tree: the files, their names, and that they agree with the code."""

import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from hotrec import APP_ID, __version__, cli, config, indicator
from hotrec import shortcuts as sc

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"


def desktop_sections():
    sections, current = {}, None
    for line in (DATA / (APP_ID + ".desktop.in")).read_text(encoding="utf-8").splitlines():
        if line.startswith("["):
            current = sections.setdefault(line.strip("[]"), {})
        elif "=" in line and current is not None:
            key, value = line.split("=", 1)
            current[key] = value
    return sections


def test_the_launcher_names_real_commands_and_the_actions_it_lists():
    sections = desktop_sections()
    main = sections["Desktop Entry"]
    assert main["Type"] == "Application" and main["Icon"] == APP_ID and main["TryExec"] == "hotrec"
    assert main["Exec"] == "hotrec setup"
    assert main["Categories"].endswith(";") and main["Actions"].endswith(";")
    actions = main["Actions"].strip(";").split(";")
    assert actions == [
        "video-audio",
        "video",
        "audio",
        "pause",
        "region-video-audio",
        "region-video",
    ]
    parser = cli.build_parser()
    for action in actions:
        section = sections["Desktop Action " + action]
        assert section["Exec"] == "hotrec " + action
        parser.parse_args(section["Exec"].split()[1:])  # the command line is one the CLI accepts
    assert set(s for s in sections if s.startswith("Desktop Action ")) == {
        "Desktop Action " + a for a in actions
    }


def test_the_autostart_entry_runs_a_command_the_cli_has_and_only_in_gnome():
    lines = (DATA / (APP_ID + "-autostart.desktop")).read_text(encoding="utf-8").splitlines()
    assert lines[0] == "[Desktop Entry]"
    entry = dict(line.split("=", 1) for line in lines[1:] if "=" in line)
    assert entry["Type"] == "Application" and entry["TryExec"] == "hotrec"
    assert entry["Exec"] == "hotrec autostart"
    cli.build_parser().parse_args(entry["Exec"].split()[1:])
    assert entry["NoDisplay"] == "true" and entry["OnlyShowIn"] == "GNOME;"
    assert entry["X-GNOME-Autostart-enabled"] == "true"
    assert entry["Icon"] == APP_ID


def test_the_spec_follows_the_version_and_installs_the_autostart_entry():
    spec = (REPO / "packaging/fedora/hotrec.spec").read_text(encoding="utf-8")
    assert re.search(r"^Version:\s+%s$" % re.escape(__version__), spec, re.MULTILINE)
    entry = "%{_sysconfdir}/xdg/autostart/%{appid}-autostart.desktop"
    files = spec.split("\n%files", 1)[1].split("\n%changelog", 1)[0]
    assert entry in files
    assert "SYSCONFDIR=%{_sysconfdir}" in spec
    assert "desktop-file-validate %{buildroot}" + entry in spec  # %check
    changelog = spec.split("%changelog\n", 1)[1]
    assert re.match(r"\* \w{3} \w{3} \d+ \d{4} .* - %s-1\n" % re.escape(__version__), changelog)


def test_the_action_names_are_the_shortcut_names():
    """One text, one translation: the launcher's actions and the GNOME shortcuts read alike."""
    sections = desktop_sections()
    names = sc.shortcut_names()
    for slug, text in names.items():
        assert sections["Desktop Action " + slug]["Name"] == text


def test_the_metadata():
    root = ET.parse(DATA / (APP_ID + ".metainfo.xml.in")).getroot()
    assert root.get("type") == "desktop-application"
    assert root.findtext("id") == APP_ID
    assert root.find("launchable").text == APP_ID + ".desktop"
    assert root.findtext("project_license") == "GPL-3.0-or-later"
    assert [b.text for b in root.find("provides")] == ["hotrec"]
    releases = root.find("releases")
    assert releases[0].get("version") == __version__
    assert len(root.find("description")) == 3


def test_the_version_is_one_number():
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r'^version = "%s"$' % re.escape(__version__), text, re.MULTILINE)
    assert re.search(r'^hotrec = "hotrec\.cli:main"$', text, re.MULTILINE)
    assert not re.search(r"^dependencies\s*=", text, re.MULTILINE)  # PyGObject: the distribution
    assert ".TH HOTREC 1" in (REPO / "packaging/man/hotrec.1").read_text(encoding="utf-8")
    assert "hotrec %s" % __version__ in (REPO / "packaging/man/hotrec.1").read_text(
        encoding="utf-8"
    )


def test_the_icons_the_code_names_exist():
    base = DATA / "icons" / "hicolor"
    for name in (indicator.ICON_RECORDING, indicator.ICON_RECORDING_OFF, indicator.ICON_PAUSED):
        svg = base / "scalable" / "status" / (name + ".svg")
        assert ET.parse(svg).getroot().tag.endswith("svg")
    assert indicator.ICON_RECORDING.startswith(APP_ID) and indicator.ICON_PAUSED.startswith(APP_ID)
    for path in (
        base / "scalable" / "apps" / (APP_ID + ".svg"),
        base / "symbolic" / "apps" / (APP_ID + "-symbolic.svg"),
    ):
        assert ET.parse(path).getroot().tag.endswith("svg")
    recording = (base / "scalable/status" / (indicator.ICON_RECORDING + ".svg")).read_text()
    paused = (base / "scalable/status" / (indicator.ICON_PAUSED + ".svg")).read_text()
    assert "#e01b24" in recording and "#f6d32d" in paused  # red = recording, yellow = paused
    off = (base / "scalable/status" / (indicator.ICON_RECORDING_OFF + ".svg")).read_text()
    assert "#e01b24" in off and 'fill="none"' in off  # the dark half is a red ring, not a dot


def test_the_manual_page_covers_every_command_key_and_setting():
    text = (REPO / "packaging/man/hotrec.1").read_text(encoding="utf-8")
    parser = cli.build_parser()
    commands = [a for a in parser._subparsers._group_actions[0].choices]
    for command in commands:
        assert command in text.replace("\\-", "-"), command
    for shortcut in sc.SHORTCUTS:
        assert shortcut.keys in text
    for key in config.KEYS:
        assert key in text
    assert "HOTREC_LOCALEDIR" in text and "hotrec.conf" in text and "felvetel.conf" in text


def test_no_flatpak_anywhere_in_the_program():
    for path in (REPO / "hotrec").rglob("*.py"):
        assert "flatpak" not in path.read_text(encoding="utf-8").lower(), path


@pytest.mark.skipif(
    shutil.which("make") is None or shutil.which("msgfmt") is None, reason="make or gettext missing"
)
def test_install_data_puts_every_file_where_the_package_expects_it(tmp_path):
    subprocess.run(
        ["make", "-C", str(REPO), "install-data", "DESTDIR=%s" % tmp_path, "PREFIX=/usr"],
        check=True,
        capture_output=True,
    )
    found = sorted(
        str(p.relative_to(tmp_path))
        for p in tmp_path.rglob("*")
        if p.is_file() and p.suffix != ".mo"
    )
    assert found == [
        "etc/xdg/autostart/%s-autostart.desktop" % APP_ID,
        "usr/share/applications/%s.desktop" % APP_ID,
        "usr/share/gnome-shell/extensions/hotrec-dot@trensoft.github.io/extension.js",
        "usr/share/gnome-shell/extensions/hotrec-dot@trensoft.github.io/logic.js",
        "usr/share/gnome-shell/extensions/hotrec-dot@trensoft.github.io/metadata.json",
        "usr/share/icons/hicolor/scalable/apps/%s.svg" % APP_ID,
        "usr/share/icons/hicolor/scalable/status/%s-paused.svg" % APP_ID,
        "usr/share/icons/hicolor/scalable/status/%s-recording-off.svg" % APP_ID,
        "usr/share/icons/hicolor/scalable/status/%s-recording.svg" % APP_ID,
        "usr/share/icons/hicolor/symbolic/apps/%s-symbolic.svg" % APP_ID,
        "usr/share/man/man1/hotrec.1",
        "usr/share/metainfo/%s.metainfo.xml" % APP_ID,
    ]
    mos = sorted(tmp_path.glob("usr/share/locale/*/LC_MESSAGES/%s.mo" % APP_ID))
    languages = re.sub(r"#[^\n]*", "", (REPO / "po/LINGUAS").read_text()).split()
    assert sorted(p.parts[-3] for p in mos) == sorted(languages)
    desktop = (tmp_path / ("usr/share/applications/%s.desktop" % APP_ID)).read_text(
        encoding="utf-8"
    )
    assert "Name[de]=" in desktop
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert path.stat().st_mode & 0o777 == 0o644, path


# -- the Shell extension (0.1.4) -------------------------------------------------------------

EXTENSION = REPO / "gnome-shell" / "hotrec-dot@trensoft.github.io"


def test_the_extension_metadata_is_what_gnome_shell_47_to_49_loads():
    import json

    meta = json.loads((EXTENSION / "metadata.json").read_text(encoding="utf-8"))
    assert meta["uuid"] == EXTENSION.name
    assert meta["shell-version"] == ["47", "48", "49"]
    assert meta["version-name"] == __version__
    assert {"name", "description"} <= set(meta)


def test_the_extension_has_exactly_the_files_the_makefile_installs():
    make = (REPO / "Makefile").read_text(encoding="utf-8")
    listed = re.search(r"for f in ([\w. ]+); do", make).group(1).split()
    assert sorted(listed) == sorted(p.name for p in EXTENSION.iterdir())


def test_the_extension_reads_the_state_file_hotrec_writes(tmp_path):
    """The two sides of the one contract: the field names of State and the directory name."""
    from dataclasses import fields

    from hotrec import recorder

    logic = (EXTENSION / "logic.js").read_text(encoding="utf-8")
    for field in fields(recorder.State):
        if field.name not in ("file", "region"):  # the dot needs neither the file nor the area
            assert field.name in logic, field.name
    assert "'state.json'" in logic and "STATE_DIR = 'hotrec'" in logic
    runtime = tmp_path / "run"
    runtime.mkdir(mode=0o700)
    assert recorder.state_dir({"XDG_RUNTIME_DIR": str(runtime)}) == runtime / "hotrec"


def test_the_extension_imports_only_what_the_shell_and_the_package_have():
    text = (EXTENSION / "extension.js").read_text(encoding="utf-8")
    imports = re.findall(r"from '([^']+)'", text)
    assert sorted(imports) == sorted(
        [
            "gi://St",
            "gi://Gio",
            "gi://GLib",
            "resource:///org/gnome/shell/extensions/extension.js",
            "resource:///org/gnome/shell/ui/main.js",
            "./logic.js",
        ]
    )
    assert "trackFullscreen: false" in text  # the point of it: above a fullscreen window


def test_the_spec_has_the_extension_subpackage_and_the_main_package_recommends_it():
    spec = (REPO / "packaging/fedora/hotrec.spec").read_text(encoding="utf-8")
    assert re.search(
        r"^Recommends:\s+%\{name\}-gnome-shell-extension = %\{version\}-%\{release\}$",
        spec,
        re.MULTILINE,
    )
    assert not re.search(r"^Requires:\s+%\{name\}-gnome-shell-extension", spec, re.MULTILINE)
    sub = spec.split("%package gnome-shell-extension", 1)[1].split("%description", 1)[0]
    assert "BuildArch:      noarch" in sub
    assert "Requires:       %{name} = %{version}-%{release}" in sub
    assert "Requires:       gnome-shell >= 47" in sub
    files = spec.split("\n%files gnome-shell-extension", 1)[1].split("\n%changelog", 1)[0]
    assert "%{_datadir}/gnome-shell/extensions/" + EXTENSION.name + "/" in files
    assert "%license LICENSE" in files
    main = spec.split("\n%files -f", 1)[1].split("\n%files gnome-shell-extension", 1)[0]
    assert "gnome-shell/extensions" not in main  # one owner for each file


def test_the_changelog_names_the_subpackage_and_the_fallback():
    spec = (REPO / "packaging/fedora/hotrec.spec").read_text(encoding="utf-8")
    entry = spec.split("%changelog\n", 1)[1].split("\n\n", 1)[0]
    assert "hotrec-gnome-shell-extension" in entry and "fallback" in entry


@pytest.mark.skipif(shutil.which("node") is None, reason="node missing")
def test_the_extension_passes_its_node_tests_against_a_fake_desktop():
    probe = subprocess.run(
        ["node", "-e", "process.exit(require('node:module').registerHooks ? 0 : 1)"],
        capture_output=True,
    )
    if probe.returncode != 0:
        pytest.skip("this node has no module.registerHooks (22.15 or newer)")
    tests = sorted(str(p) for p in (REPO / "tests" / "js").glob("*.test.mjs"))
    result = subprocess.run(
        ["node", "--import", str(REPO / "tests/js/fake-gnome.mjs"), "--test", *tests],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-1000:]
