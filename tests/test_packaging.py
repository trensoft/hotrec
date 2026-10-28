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
    assert actions == ["video-audio", "video", "audio", "pause"]
    parser = cli.build_parser()
    for action in actions:
        section = sections["Desktop Action " + action]
        assert section["Exec"] == "hotrec " + action
        parser.parse_args(section["Exec"].split()[1:])  # the command line is one the CLI accepts
    assert set(s for s in sections if s.startswith("Desktop Action ")) == {
        "Desktop Action " + a for a in actions
    }


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
    for name in (indicator.ICON_RECORDING, indicator.ICON_PAUSED):
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
        "usr/share/applications/%s.desktop" % APP_ID,
        "usr/share/icons/hicolor/scalable/apps/%s.svg" % APP_ID,
        "usr/share/icons/hicolor/scalable/status/%s-paused.svg" % APP_ID,
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
