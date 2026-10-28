# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path

from hotrec import config


def test_the_first_run_writes_the_defaults(env):
    cfg, warnings = config.load(env)
    path = config.config_path(env)
    assert warnings == []
    assert path == Path(env["HOME"]) / ".config" / "hotrec.conf"
    assert path.is_file()
    assert (cfg.container, cfg.video_kbps, cfg.fps, cfg.aac_kbps, cfg.mp3_kbps) == (
        "mkv",
        12000,
        30,
        160,
        192,
    )
    assert cfg.folder == "$HOME/Videos/Hotrec"
    assert cfg.folder_path(env) == Path(env["HOME"]) / "Videos" / "Hotrec"
    # what was written reads back as the same settings, with no warning
    again, warnings = config.load(env)
    assert again == cfg and warnings == []


def test_the_default_file_has_no_encoder_choice(env):
    config.load(env)
    text = config.config_path(env).read_text(encoding="utf-8")
    for word in ("cpu", "CPU", "x264", "ENCODER", "KODOLO"):
        assert word not in text


def test_xdg_config_home_is_honoured_and_a_relative_one_is_not(env):
    env = dict(env, XDG_CONFIG_HOME="/somewhere/else")
    assert config.config_path(env) == Path("/somewhere/else/hotrec.conf")
    env = dict(env, XDG_CONFIG_HOME="relative")
    assert config.config_path(env) == Path(env["HOME"]) / ".config" / "hotrec.conf"


def test_the_videos_folder_comes_from_user_dirs(env):
    home = env["HOME"]
    dirs = Path(env["XDG_CONFIG_HOME"]) / "user-dirs.dirs"
    dirs.parent.mkdir(parents=True)
    dirs.write_text('# comment\nXDG_VIDEOS_DIR="$HOME/Videók"\n', encoding="utf-8")
    assert config.videos_dir(env) == "$HOME/Videók"
    dirs.write_text('XDG_VIDEOS_DIR="%s/Filmek"\n' % home, encoding="utf-8")
    assert config.videos_dir(env) == "$HOME/Filmek"
    dirs.write_text('XDG_VIDEOS_DIR="/mnt/elsewhere"\n', encoding="utf-8")
    assert config.videos_dir(env) == "$HOME/Videos"


def test_parse_values_quotes_and_comments():
    values, problems = config.parse(
        "# a comment\n"
        "A=1   # trailing comment\n"
        'B="two words"  # after the quote\n'
        "C='single'\n"
        "D=has#hash\n"
        "E=\n"
        "A=3\n"
        "this is not a setting\n"
        'F="open\n'
    )
    assert values == {"A": "3", "B": "two words", "C": "single", "D": "has#hash", "E": ""}
    assert len(problems) == 2 and "line 8" in problems[0] and "line 9" in problems[1]


def test_a_bad_value_gets_the_default_and_a_warning(env):
    cfg, warnings = config.build(
        {
            "CONTAINER": "avi",
            "VIDEO_KBPS": "lots",
            "FPS": "0",
            "AAC_KBPS": "99999",
            "MP3_KBPS": "-5",
            "FOLDER": "   ",
        },
        env,
    )
    assert cfg == config.default_config(env)
    assert len(warnings) == 6
    assert any("CONTAINER=avi" in w for w in warnings)


def test_good_values_and_case_of_the_container(env):
    cfg, warnings = config.build(
        {
            "CONTAINER": "MP4",
            "VIDEO_KBPS": "8000",
            "FPS": "60",
            "AAC_KBPS": "128",
            "MP3_KBPS": "320",
        },
        env,
    )
    assert warnings == []
    assert (cfg.container, cfg.video_kbps, cfg.fps, cfg.aac_kbps, cfg.mp3_kbps) == (
        "mp4",
        8000,
        60,
        128,
        320,
    )


def test_numbers_must_be_plain_ascii_digits(env):
    for bad in ("12.5", "1e3", "٣٠", " ", "+30", "0x1e"):
        cfg, warnings = config.build({"FPS": bad}, env)
        assert cfg.fps == 30 and len(warnings) == 1, bad


def test_the_encoder_key_is_gone_not_just_ignored_silently(env):
    cfg, warnings = config.build({"ENCODER": "cpu", "KODOLO": "cpu"}, env)
    assert cfg == config.default_config(env)
    assert warnings == ["ENCODER is not a setting, ignored", "KODOLO is not a setting, ignored"]


def test_a_folder_with_both_kinds_of_quote_is_refused(env):
    cfg, warnings = config.build({"FOLDER": "a\"b'c"}, env)
    assert cfg.folder == config.default_config(env).folder and len(warnings) == 1


def test_a_folder_with_a_double_quote_survives_the_write(env):
    cfg, _ = config.build({"FOLDER": 'a"b'}, env)
    values, problems = config.parse(config.render(cfg))
    assert problems == [] and values["FOLDER"] == 'a"b'


def test_expand_knows_home_only(env):
    home = env["HOME"]
    assert config.expand("$HOME/a", env) == home + "/a"
    assert config.expand("${HOME}/a", env) == home + "/a"
    assert config.expand("~/a", env) == home + "/a"
    assert config.expand("~other/a", env) == "~other/a"
    assert config.expand("$HOMEWORK/a", env) == "$HOMEWORK/a"
    assert config.expand("$(touch x)/$USER", env) == "$(touch x)/$USER"


def test_nothing_in_the_file_is_run(env, tmp_path):
    marker = tmp_path / "ran"
    path = config.config_path(env)
    path.parent.mkdir(parents=True)
    path.write_text('FOLDER="$(touch %s)"\nFPS=`touch %s`\n' % (marker, marker), encoding="utf-8")
    cfg, warnings = config.load(env)
    assert not marker.exists()
    assert cfg.folder == "$(touch %s)" % marker
    assert cfg.fps == 30 and any("FPS" in w for w in warnings)


def test_the_old_conf_is_imported_once(env):
    old = config.old_config_path(env)
    old.parent.mkdir(parents=True)
    old_text = (
        "# felvetel\n"
        'MAPPA="$HOME/Videók/Felvételek"   # ide ment\n'
        "KONTENER=mp4\n"
        "KODOLO=cpu\n"
        "VIDEO_KBPS=8000\n"
        "FPS=60\n"
        "AAC_KBPS=128\n"
        "MP3_KBPS=256\n"
    )
    old.write_text(old_text, encoding="utf-8")
    cfg, warnings = config.load(env)
    assert warnings == []
    assert cfg.folder == "$HOME/Videók/Felvételek"
    assert (cfg.container, cfg.video_kbps, cfg.fps, cfg.aac_kbps, cfg.mp3_kbps) == (
        "mp4",
        8000,
        60,
        128,
        256,
    )
    new_text = config.config_path(env).read_text(encoding="utf-8")
    assert "Imported from" in new_text
    assert "KODOLO" not in new_text and "cpu" not in new_text.replace("Imported", "")
    assert old.read_text(encoding="utf-8") == old_text  # left alone
    # the user edits the new file; a later run does not take the old one again
    config.config_path(env).write_text("FPS=24\n", encoding="utf-8")
    old.write_text("FPS=99\n", encoding="utf-8")
    assert config.load(env)[0].fps == 24


def test_the_old_conf_with_bad_lines_still_gives_a_working_file(env):
    old = config.old_config_path(env)
    old.parent.mkdir(parents=True)
    old.write_text("source /etc/profile\nFPS=abc\nKONTENER=avi\n", encoding="utf-8")
    cfg, warnings = config.load(env)
    assert cfg == config.default_config(env)
    assert len(warnings) == 3
    assert config.load(env)[1] == []  # the file that was written is clean


def test_an_unreadable_old_conf_falls_back_to_the_defaults(env):
    old = config.old_config_path(env)
    old.mkdir(parents=True)  # a directory: is_file() is False, so it is simply not there
    cfg, warnings = config.load(env)
    assert cfg == config.default_config(env) and warnings == []


def test_a_conf_that_cannot_be_read_gives_the_defaults(env):
    path = config.config_path(env)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"\xff\xfe\x00bad")
    cfg, warnings = config.load(env)
    assert cfg == config.default_config(env)
    assert len(warnings) == 1 and "cannot be read" in warnings[0]


def test_a_config_directory_that_cannot_be_written_is_a_warning_not_a_crash(env, tmp_path):
    blocked = tmp_path / "file"
    blocked.write_text("x")
    env = dict(env, XDG_CONFIG_HOME=str(blocked / "sub"))
    cfg, warnings = config.load(env)
    assert cfg == config.default_config(env)
    assert len(warnings) == 1 and "cannot be written" in warnings[0]
