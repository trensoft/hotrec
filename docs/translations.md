# Translations

40 catalogs, all in `po/LINGUAS`: German, Spanish, French,
Hungarian, Italian, Bulgarian, Catalan, Czech, Danish, Greek, Estonian, Finnish, Irish, Croatian,
Lithuanian, Latvian, Maltese, Dutch, Polish, Portuguese (`pt`), Brazilian Portuguese (`pt_BR`),
Romanian, Slovak, Slovenian, Serbian (Cyrillic), Swedish, Norwegian Bokmål (`nb`), Ukrainian,
Russian, Japanese, Simplified Chinese (`zh_CN`), Traditional Chinese (`zh_TW`), Arabic, Hebrew,
Hindi, Filipino (`fil`), Indonesian, Thai, Vietnamese, Korean.

**Who translated them.** With AI assistance; no native speaker has read them. The header of each
says `Last-Translator: AI-assisted (Claude), not reviewed by a native speaker`. The tests check that
a catalog is whole, has the right header and placeholders, is in the script of its language and is
wired in; not that the language is good. Corrections: a pull request on `po/<lang>.po`.

There is no per-language glossary file yet: the interface has 27 strings,
and the words that must agree (record, pause, resume, stop, save) are in them all.

## What is translated

Every user-facing string goes through `_()` inside a function (one plain literal; `tools/i18n.sh
check` and `tests/test_i18n_source.py` enforce it): the notifications, the dot's menu, the names of
the GNOME shortcuts (translated when `shortcuts install` runs, in the language of that session). The
launcher and the AppStream metadata are templates (`data/*.in`) translated at build time. Not
translated: the log, `--help`, the settings file, the file names of recordings.

## How the language is chosen

`hotrec/i18n.py`, `setup()`, first thing in `main()`: `LANGUAGE`, `LC_ALL`, `LC_MESSAGES`, `LANG` in
that order; catalogs at `<localedir>/<lang>/LC_MESSAGES/io.github.trensoft.hotrec.mo`, the
directory being `$HOTREC_LOCALEDIR` or the system one (`run.sh` points it at catalogs it builds).
A missing catalog is English. A catalog that cannot be used is English plus one WARNING line, never
an error. The shortcuts the desktop runs get the language of the *session*, so a notification is in
the language the desktop speaks.

## Adding or changing a language

1. `tools/i18n.sh update` (writes `po/messages.pot`, not in git, and merges it into the catalogs).
2. New language: `msginit --no-translator -l <lang> -i po/messages.pot -o po/<lang>.po`, set
   `charset=UTF-8`, the true `Plural-Forms`, the `Language:` and `Last-Translator:` header lines; add
   `<lang>` to `po/LINGUAS` (an underscore, never `pt-BR`).
3. `tools/i18n.sh check`.

`tools/i18n.sh build DIR` compiles the catalogs, `tools/i18n.sh data DIR` writes the translated
launcher and metadata.
