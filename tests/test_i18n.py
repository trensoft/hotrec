# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

"""The language the interface speaks, from real catalogs built by tools/i18n.sh."""

import gettext
import logging
import shutil
import subprocess
from pathlib import Path

import pytest

from hotrec import APP_ID, _, i18n

REPO = Path(__file__).resolve().parent.parent
needs_gettext = pytest.mark.skipif(shutil.which("msgfmt") is None, reason="msgfmt not installed")


@pytest.fixture(autouse=True)
def clean_gettext(env, monkeypatch):
    """gettext keeps the domain, its directory and the loaded catalogs in module state."""
    saved = gettext.bindtextdomain(APP_ID)
    gettext._translations.clear()
    yield
    gettext._translations.clear()
    gettext.bindtextdomain(APP_ID, saved)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    if shutil.which("msgfmt") is None:
        pytest.skip("msgfmt not installed")
    out = tmp_path_factory.mktemp("locale")
    subprocess.run([str(REPO / "tools" / "i18n.sh"), "build", str(out)], check=True)
    return out


def start(monkeypatch, localedir, **variables):
    monkeypatch.setenv("HOTREC_LOCALEDIR", str(localedir))
    for name in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(name, raising=False)
    for name, value in variables.items():
        monkeypatch.setenv(name, value)
    gettext._translations.clear()
    return i18n.setup()


def test_without_a_catalog_the_interface_is_english(monkeypatch, tmp_path):
    status = start(monkeypatch, tmp_path, LANG="hu_HU.UTF-8")
    assert status.catalogs == ()
    assert _("Recording saved") == "Recording saved"


@needs_gettext
def test_the_session_language_is_used(monkeypatch, built):
    status = start(monkeypatch, built, LANG="hu_HU.UTF-8")
    assert len(status.catalogs) == 1 and status.catalogs[0].endswith(
        "hu/LC_MESSAGES/%s.mo" % APP_ID
    )
    assert _("Recording saved") == "A felvétel mentve"
    assert _("Stop and save") == "Leállítás és mentés"


@needs_gettext
@pytest.mark.parametrize(
    "lang,expected",
    [
        ("de_DE.UTF-8", "Aufnahme gespeichert"),
        ("pt_BR.UTF-8", "Gravação salva"),
        ("pt_PT.UTF-8", "Gravação guardada"),
        ("zh_CN.UTF-8", "录制已保存"),
        ("zh_TW.UTF-8", "錄製已儲存"),
        ("ja_JP.UTF-8", "録画を保存しました"),
        ("ar_EG.UTF-8", "تم حفظ التسجيل"),
        ("fil_PH.UTF-8", "Na-save ang recording"),
    ],
)
def test_regional_names_find_their_catalog(monkeypatch, built, lang, expected):
    start(monkeypatch, built, LANG=lang)
    assert _("Recording saved") == expected


@needs_gettext
def test_language_list_falls_back(monkeypatch, built):
    start(monkeypatch, built, LANGUAGE="xx:de:hu")
    assert _("Resume") == "Fortsetzen"


@needs_gettext
def test_c_and_an_unknown_language_stay_english(monkeypatch, built):
    start(monkeypatch, built, LANG="C")
    assert _("Resume") == "Resume"
    start(monkeypatch, built, LANG="xx_XX.UTF-8")
    assert _("Resume") == "Resume"


@needs_gettext
def test_every_shipped_language_translates_the_dot_and_the_notification(monkeypatch, built):
    from hotrec import indicator
    from hotrec.recorder import State

    names = sorted(path.name for path in built.iterdir())
    assert len(names) == 40
    for name in names:
        start(monkeypatch, built, LANGUAGE=name)
        view = indicator.view(State(1, 2, "video", "/f"))
        assert view.description != "Recording", name
        assert view.pause_label and _("Recording saved") != "Recording saved", name


def test_a_catalog_that_is_not_a_catalog_leaves_english_and_one_warning(
    monkeypatch, tmp_path, caplog
):
    folder = tmp_path / "hu" / "LC_MESSAGES"
    folder.mkdir(parents=True)
    (folder / ("%s.mo" % APP_ID)).write_bytes(b"this is not a catalog at all")
    with caplog.at_level(logging.WARNING, logger="hotrec.i18n"):
        status = start(monkeypatch, tmp_path, LANG="hu_HU.UTF-8")
    assert status.catalogs == ()
    assert _("Recording saved") == "Recording saved"  # does not raise
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and "cannot be used" in warnings[0].getMessage()


def test_a_truncated_catalog_does_not_stop_the_program(monkeypatch, tmp_path):
    folder = tmp_path / "de" / "LC_MESSAGES"
    folder.mkdir(parents=True)
    (folder / ("%s.mo" % APP_ID)).write_bytes(b"\xde\x12\x04\x95" + b"\x00" * 36)
    start(monkeypatch, tmp_path, LANG="de_DE.UTF-8")
    assert _("Resume") == "Resume"


def test_log_status_names_language_and_catalog(monkeypatch, tmp_path, caplog):
    status = start(monkeypatch, tmp_path, LANG="hu_HU.UTF-8")
    with caplog.at_level(logging.INFO, logger="hotrec.i18n"):
        i18n.log_status(status)
    line = caplog.records[-1].getMessage()
    assert "LANG=hu_HU.UTF-8" in line and "LANGUAGE=unset" in line and "catalog none" in line
