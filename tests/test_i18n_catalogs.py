# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

"""The 40 catalogs: whole, consistent, wired in. Not that the language is good (nobody who speaks
it has read them, see docs/translations.md)."""

import ast
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PO = REPO / "po"


def linguas():
    text = re.sub(r"#[^\n]*", "", (PO / "LINGUAS").read_text(encoding="utf-8"))
    return text.split()


def entries(path):
    """``[(msgid, msgstr, flags)]`` without the header; strings are joined and unquoted."""
    result = []
    block = path.read_text(encoding="utf-8").split("\n\n")
    for text in block[1:]:
        if not text.strip():
            continue
        msgid = msgstr = ""
        target = None
        flags = []
        for line in text.splitlines():
            if line.startswith("#,"):
                flags += [f.strip() for f in line[2:].split(",")]
            elif line.startswith("msgid "):
                target, msgid = "id", ast.literal_eval(line[6:])
            elif line.startswith("msgstr "):
                target, msgstr = "str", ast.literal_eval(line[7:])
            elif line.startswith('"'):
                if target == "id":
                    msgid += ast.literal_eval(line)
                elif target == "str":
                    msgstr += ast.literal_eval(line)
        result.append((msgid, msgstr, flags))
    return result


def header(path):
    text = path.read_text(encoding="utf-8").split("\n\n")[0]
    joined = "".join(ast.literal_eval(line) for line in text.splitlines() if line.startswith('"'))
    return dict(line.split(": ", 1) for line in joined.split("\n") if ": " in line)


LANGS = linguas()
ENGLISH = {m for m, _s, _f in entries(PO / "hu.po")}


def test_forty_languages_all_wired():
    assert len(LANGS) == 40 and len(set(LANGS)) == 40
    assert sorted(p.stem for p in PO.glob("*.po")) == sorted(LANGS)
    for expected in (
        "de",
        "es",
        "fr",
        "hu",
        "it",
        "pt_BR",
        "zh_CN",
        "zh_TW",
        "ar",
        "he",
        "ja",
        "ko",
    ):
        assert expected in LANGS
    for name in LANGS:
        assert re.fullmatch(r"[a-z]{2,3}(_[A-Z]{2})?", name), name  # pt_BR, never pt-BR


@pytest.mark.parametrize("lang", LANGS)
def test_header(lang):
    head = header(PO / ("%s.po" % lang))
    assert head["Content-Type"] == "text/plain; charset=UTF-8"
    assert head["Language"] == lang
    assert re.fullmatch(r"nplurals=\d+; plural=.+;", head["Plural-Forms"]), head["Plural-Forms"]
    assert head["Last-Translator"] == "AI-assisted (Claude), not reviewed by a native speaker"


@pytest.mark.parametrize("lang", LANGS)
def test_every_string_is_translated_once(lang):
    items = entries(PO / ("%s.po" % lang))
    ids = [m for m, _s, _f in items]
    assert len(ids) == len(set(ids))
    assert set(ids) == ENGLISH
    for msgid, msgstr, flags in items:
        assert msgstr.strip(), (lang, msgid)
        assert "fuzzy" not in flags, (lang, msgid)
        assert msgstr == msgstr.strip(), (lang, msgid)


@pytest.mark.parametrize("lang", LANGS)
def test_placeholders_match(lang):
    for msgid, msgstr, _f in entries(PO / ("%s.po" % lang)):
        assert sorted(re.findall(r"%[sd]", msgid)) == sorted(re.findall(r"%[sd]", msgstr)), (
            lang,
            msgid,
        )
        assert not re.search(r"%(?![sd%])", msgstr.replace("%%", "")), (lang, msgid)


@pytest.mark.parametrize("lang", LANGS)
def test_the_key_names_in_the_notification_survive(lang):
    for msgid, msgstr, _f in entries(PO / ("%s.po" % lang)):
        if msgid.startswith("Ctrl+Shift+F9"):
            for key in ("F9", "F10", "F11", "F12"):
                assert key in msgstr, (lang, key)


@pytest.mark.parametrize("lang", LANGS)
def test_the_key_names_in_the_shortcuts_window_survive(lang):
    """The keys are named as they are printed on the keyboard, whatever the language."""
    for msgid, msgstr, _f in entries(PO / ("%s.po" % lang)):
        if msgid.startswith("Use Ctrl, Alt or Super"):
            for key in ("Ctrl", "Alt", "Super"):
                assert key in msgstr, (lang, key)
        if msgid.startswith("Click a field"):
            assert ("Échap" if lang == "fr" else "Esc") in msgstr, lang  # the French key cap
            assert "Escape" not in msgstr, lang


@pytest.mark.parametrize("lang", LANGS)
def test_the_shortcuts_window_and_menu_are_translated(lang):
    translated = {m: s for m, s, _f in entries(PO / ("%s.po" % lang))}
    for msgid in (
        "Set keyboard shortcuts...",
        "Keyboard shortcuts",
        "Click a field, then press the new keys. Escape cancels.",
        "Save",
        "Press the keys...",
        "Use Ctrl, Alt or Super together with the key.",
        "Two of the shortcuts have the same keys.",
    ):
        assert translated[msgid], (lang, msgid)
    assert translated["Set keyboard shortcuts..."].endswith("...")
    assert translated["Press the keys..."].endswith("...")


NEW_IN_013 = (
    "The VA-API video driver is missing or does not work. On Intel graphics, install "
    "intel-media-driver (RPM Fusion nonfree), then try again.",
    "The video encoder did not start. The graphics driver may lack hardware video encoding "
    "(VA-API or NVENC).",
    "The recording stopped",
    "Save videos in",
    "Save audio in",
    "Choose a folder",
    "Default",
    "Could not save the folders",
)


@pytest.mark.parametrize("lang", LANGS)
def test_the_encoder_and_folder_texts_are_translated(lang):
    """0.1.3: the notification for a missing encoder driver and the folder rows."""
    translated = {m: s for m, s, f in entries(PO / ("%s.po" % lang)) if "fuzzy" not in f}
    for msgid in NEW_IN_013:
        assert translated.get(msgid), (lang, msgid)


@pytest.mark.parametrize("lang", LANGS)
def test_the_driver_package_and_the_names_survive_in_the_notification(lang):
    translated = {m: s for m, s, _f in entries(PO / ("%s.po" % lang))}
    driver = translated[NEW_IN_013[0]]
    for word in ("intel-media-driver", "RPM Fusion", "VA-API"):
        assert word in driver, (lang, word)
    assert "VA-API" in translated[NEW_IN_013[1]] and "NVENC" in translated[NEW_IN_013[1]], lang


DOT_EXTENSION_TEXT = (
    "The blinking red dot over a fullscreen video is on. If you do not see it yet, "
    "log out and in once. You can turn it off in the Extensions app."
)


DOT_EXTENSION_KNOWN_TEXT = (
    "The blinking red dot over a fullscreen video is on. You can turn it off in the Extensions app."
)


@pytest.mark.parametrize("lang", LANGS)
def test_the_dot_extension_notifications_are_translated(lang):
    """0.1.4: the two texts of ``hotrec autostart`` switching the Shell extension on: with and
    without the log out (the Shell already knows the extension)."""
    translated = {m: s for m, s, f in entries(PO / ("%s.po" % lang)) if "fuzzy" not in f}
    assert translated.get(DOT_EXTENSION_TEXT), lang
    known = translated.get(DOT_EXTENSION_KNOWN_TEXT)
    assert known and known != translated[DOT_EXTENSION_TEXT], lang
    assert len(known) < len(translated[DOT_EXTENSION_TEXT]), lang


SAME_AS_ENGLISH = {"Hotrec"}
PAUSE_IS_PAUSE = {"de", "fr", "da", "nb"}
DEFAULT_IS_DEFAULT = {"fil"}  # the word Filipino desktops use


@pytest.mark.parametrize("lang", LANGS)
def test_nothing_was_left_in_english(lang):
    for msgid, msgstr, _f in entries(PO / ("%s.po" % lang)):
        if msgid in SAME_AS_ENGLISH or (msgid == "Pause" and lang in PAUSE_IS_PAUSE):
            continue
        if msgid == "Default" and lang in DEFAULT_IS_DEFAULT:
            continue
        assert msgstr != msgid, (lang, msgid)


SCRIPTS = {
    "bg": r"[Ѐ-ӿ]",
    "ru": r"[Ѐ-ӿ]",
    "uk": r"[Ѐ-ӿ]",
    "sr": r"[Ѐ-ӿ]",
    "el": r"[Ͱ-Ͽ]",
    "ar": r"[؀-ۿ]",
    "he": r"[֐-׿]",
    "hi": r"[ऀ-ॿ]",
    "th": r"[฀-๿]",
    "ja": r"[぀-ヿ一-鿿]",
    "ko": r"[가-힯]",
    "zh_CN": r"[一-鿿]",
    "zh_TW": r"[一-鿿]",
}


@pytest.mark.parametrize("lang", sorted(SCRIPTS))
def test_the_script_of_the_language(lang):
    for msgid, msgstr, _f in entries(PO / ("%s.po" % lang)):
        if msgid != "Hotrec":
            assert re.search(SCRIPTS[lang], msgstr), (lang, msgid)


def test_serbian_is_cyrillic_and_the_traditional_chinese_is_not_the_simplified():
    simplified = {m: s for m, s, _f in entries(PO / "zh_CN.po")}
    traditional = {m: s for m, s, _f in entries(PO / "zh_TW.po")}
    assert simplified["Stop and save"] != traditional["Stop and save"]
    assert simplified["Recording saved"] != traditional["Recording saved"]


needs_gettext = pytest.mark.skipif(shutil.which("msgfmt") is None, reason="gettext not installed")


@needs_gettext
def test_the_tool_check_passes():
    result = subprocess.run(
        [str(REPO / "tools" / "i18n.sh"), "check"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


@needs_gettext
def test_the_launcher_and_metadata_carry_the_translations(tmp_path):
    subprocess.run([str(REPO / "tools" / "i18n.sh"), "data", str(tmp_path)], check=True)
    desktop = (tmp_path / "io.github.trensoft.hotrec.desktop").read_text(encoding="utf-8")
    metainfo = (tmp_path / "io.github.trensoft.hotrec.metainfo.xml").read_text(encoding="utf-8")
    assert "Name[hu]=Képernyő és hang felvétele" in desktop
    assert "Name[ja]=" in desktop and "Comment[de]=" in desktop
    assert '<summary xml:lang="fr">' in metainfo
    assert metainfo.count("<summary xml:lang=") == 40
