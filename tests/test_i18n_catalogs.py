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
    assert (
        head["Last-Translator"] == "AI-assisted (Claude, Gemini), not reviewed by a native speaker"
    )


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
    placeholder = r"%(?:\.\d)?[sdf]"  # %s, %d, and %.1f of the bit rate
    for msgid, msgstr, _f in entries(PO / ("%s.po" % lang)):
        assert re.findall(placeholder, msgid) == re.findall(placeholder, msgstr), (lang, msgid)
        assert not re.search(r"%(?![sdf%]|\.\d)", msgstr.replace("%%", "")), (lang, msgid)


@pytest.mark.parametrize("lang", LANGS)
def test_the_key_names_in_the_notification_survive(lang):
    for msgid, msgstr, _f in entries(PO / ("%s.po" % lang)):
        if msgid.startswith("Ctrl+Shift+F9"):
            for key in ("F9", "F10", "F11", "F12"):
                assert key in msgstr, (lang, key)


@pytest.mark.parametrize("lang", LANGS)
def test_the_area_keys_in_the_notification_and_the_crop_note_are_translated(lang):
    seen = set()
    for msgid, msgstr, _f in entries(PO / ("%s.po" % lang)):
        if msgid.startswith("Ctrl+Shift+F7"):
            seen.add("keys")
            assert "F7" in msgstr and "F8" in msgstr, lang
        if msgid.startswith("Only the view is cropped"):
            seen.add("crop")
            assert msgstr.strip() and msgstr != msgid, lang
    assert seen == {"keys", "crop"}, lang


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
def test_the_settings_window_and_menu_are_translated(lang):
    translated = {m: s for m, s, _f in entries(PO / ("%s.po" % lang))}
    for msgid in (
        "Settings…",
        "Settings",
        "About",
        "Keyboard shortcuts",
        "Click a field, then press the new keys. Escape cancels.",
        "Press the keys...",
        "Use Ctrl, Alt or Super together with the key.",
        "Two of the shortcuts have the same keys.",
    ):
        assert translated[msgid], (lang, msgid)
    assert translated["Press the keys..."].endswith("...")


@pytest.mark.parametrize("lang", LANGS)
def test_an_ellipsis_in_the_english_is_the_one_character_in_the_translation(lang):
    """The Settings strings keep the character U+2026 where the English has it, not three dots."""
    for msgid, msgstr, _f in entries(PO / ("%s.po" % lang)):
        if msgid.endswith("\u2026"):
            assert msgstr.endswith("\u2026"), (lang, msgid)
            assert "..." not in msgstr, (lang, msgid)


@pytest.mark.parametrize("lang", LANGS)
def test_the_names_that_are_not_translated_survive(lang):
    """Formats and units are written as they are everywhere (spec of the Settings translation)."""
    translated = {m: s for m, s, _f in entries(PO / ("%s.po" % lang))}
    for name in ("H.264", "H.265"):
        for msgid, msgstr in translated.items():
            if name in msgid:
                assert name in msgstr, (lang, msgid)
    assert "AAC" in translated[SOUND_NOTE]
    assert "H.265" in translated[H265_NOTE] and "Windows" in translated[H265_NOTE]
    for msgid in ("%d kbit/s", "%.1f Mbit/s", "%d fps"):
        assert re.search(r"kbit/s|Mbit/s|fps", translated[msgid]) or lang in LOCALISED_UNITS, (
            lang,
            msgid,
        )


SOUND_NOTE = "Applies only to sound-only recordings. With video, the sound is always AAC."
H265_NOTE = "H.265 videos may need an extra codec to play on Windows and in some browsers."
LOCALISED_UNITS = {
    "ar",
    "he",
    "hi",
    "th",
    "ja",
    "ko",
    "zh_CN",
    "zh_TW",
    "ru",
    "uk",
    "bg",
    "sr",
    "el",
}


NEW_IN_013 = (
    "The VA-API video driver is missing or does not work. On Intel graphics, install "
    "intel-media-driver (RPM Fusion nonfree), then try again.",
    "The video encoder did not start. The graphics driver may lack hardware video encoding "
    "(VA-API or NVENC).",
    "The recording stopped",
    "Choose a folder",
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


@pytest.mark.parametrize("lang", LANGS)
def test_the_quit_line_is_translated_once_in_every_catalog(lang):
    found = [(m, s) for m, s, _f in entries(PO / ("%s.po" % lang)) if m == "Quit"]
    assert len(found) == 1 and found[0][1].strip(), lang
    assert found[0][1] != "Quit", lang


def test_the_hungarian_quit_line_is_the_word_attila_chose():
    translated = {m: s for m, s, _f in entries(PO / "hu.po")}
    assert translated["Quit"] == "Kilépés"


SAME_AS_ENGLISH = {"Hotrec"}
PAUSE_IS_PAUSE = {"de", "fr", "da", "nb"}
# Units are written alike in every language. The rest is the list of what the Gemini translation of
# the Settings strings (kept word for word, see docs/translations.md) leaves as the English word:
# a word that really is the same ("Version", "Video", "Website" in the languages named) or that
# Maltese and Filipino desktops keep in English. Any other string left in English fails the test.
UNITS = {"%d kbit/s", "%.1f Mbit/s", "%d fps"}
SAME_IN = {
    "Version %s": {"de", "fr", "da", "sv"},
    "Website": {"de", "nl", "fil"},
    "Video": {"de", "it", "cs", "da", "et", "fi", "hr", "lv", "nl", "ro", "sk", "sl", "sv"}
    | {"nb", "fil", "id", "vi"},
    "Settings": {"mt"},
    "Settings…": {"mt"},
    "Frame rate": {"mt", "fil"},
    "Folders": {"mt"},
    "Video codec": {"fil"},
    "Video bitrate": {"fil"},
}


@pytest.mark.parametrize("lang", LANGS)
def test_nothing_was_left_in_english(lang):
    for msgid, msgstr, _f in entries(PO / ("%s.po" % lang)):
        if msgid in SAME_AS_ENGLISH or msgid in UNITS or lang in SAME_IN.get(msgid, ()):
            continue
        if msgid == "Pause" and lang in PAUSE_IS_PAUSE:
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
        if msgid != "Hotrec" and msgid not in UNITS:  # a unit may stay in Latin letters
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
