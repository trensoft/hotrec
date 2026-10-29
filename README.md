# Hotrec

Screen and sound recorder for GNOME on Wayland, driven by keyboard shortcuts. Made for webinars,
where OBS cannot be started from the keyboard on Wayland unless its own window is in front: the
keys here are GNOME's own custom shortcuts, so they work in every window.

| Key | What it does |
|---|---|
| Ctrl+Shift+F9 | record the screen and the sound |
| Ctrl+Shift+F10 | record the screen only |
| Ctrl+Shift+F11 | record the sound only (MP3) |
| Ctrl+Shift+F12 | pause, and resume |

The same key stops and saves the recording that runs (any of F9, F10, F11 does, whichever started
it). While a recording runs, a red blinking dot in the top bar shows it, a yellow steady one that it is paused;
its menu has Pause/Resume and Stop and save.

At the top of that menu, in grey, are the four keys as GNOME has them now ("Ctrl+Shift+F9 - Record
screen and sound"). The dot that stays in the top bar after login also has **Set keyboard
shortcuts...**: a small window with a field for each shortcut. Click a field, press the new keys
(Escape gives up; a letter alone is refused, a function key may stand alone), then Save. The window
writes the GNOME custom keybindings with the same code as `hotrec shortcuts install`, so a key that
another program's custom shortcut already uses is refused and said so, and nothing of other
programs is overwritten. The version and the maker are at the bottom of the window.

The screen is recorded by `gpu-screen-recorder` (portal mode: the desktop asks which screen, once,
and remembers), encoded as H.264 by the graphics hardware (NVENC, VA-API). The sound of the video
is AAC; a sound-only recording is `ffmpeg` writing MP3. There is no software encoder.

## Set it up

```
hotrec shortcuts install        # or open "Hotrec" in the launcher: it does the same
```

This adds the four keys to the custom keyboard shortcuts of GNOME and leaves yours alone. If one of
the keys is taken by another custom shortcut, nothing is changed and the command says which.
`hotrec shortcuts remove` takes them out again.

With the package installed there is nothing to do: at the next login of a GNOME session the
autostart entry runs `hotrec autostart`, which sets the keys once per user (the file
`~/.local/state/hotrec/shortcuts-installed` says it was done; delete it to have it done again) and
keeps the Hotrec dot in the top bar, one at a time. The keys of the prototype this program grew out
of (custom shortcuts that run `felvetel.sh kepeshang|kep|hang|szunet`, or `felvetel-<word>`) are
replaced by the Hotrec ones; any other custom shortcut stays. To switch the autostart off, copy
`/etc/xdg/autostart/io.github.trensoft.hotrec-autostart.desktop` to `~/.config/autostart/` and add
`Hidden=true`.

The dot over a fullscreen video: the top bar, and the dot in it, are out of sight when a video plays
fullscreen. The subpackage `hotrec-gnome-shell-extension` (GNOME Shell 47-49; `hotrec` recommends it,
so `dnf` installs it with it) has a Shell extension that draws a blinking red dot in the top right
corner, above everything, while Hotrec records (a steady yellow one while paused). It reads only the
state file Hotrec keeps while it records, and runs no timer otherwise. `hotrec autostart` switches it
on once per user at login (the GSettings key `org.gnome.shell enabled-extensions`) and says so in a
notification. A running Shell learns about a new extension only at the next login: when the package
was installed after the login, the notification says to **log out and in once**; when it was already
there, the Shell knows the extension, takes the setting at once, and the notification does not ask for it. To turn it off use the Extensions app: it is not turned on again (the file
`~/.local/state/hotrec/dot-extension-offered` records that it was offered; delete it to be offered
again). Whether the screen recording itself contains the dot has to be seen on the real machine: if
it does, switch the extension off and rely on the tray dot.

From a checkout, without installing: `./run.sh shortcuts install --command "$PWD/run.sh"`.

## Settings

`~/.config/hotrec.conf`, written on the first run (`$XDG_CONFIG_HOME` is honoured):

```
FOLDER="$HOME/Videos/Hotrec"   # where recordings are saved
# VIDEO_FOLDER=                # not set: the FOLDER above (the shortcuts window sets these two)
# AUDIO_FOLDER=
CONTAINER=mkv                  # mkv (plays back even if cut short) or mp4
VIDEO_KBPS=12000               # video bit rate, kbit/s
FPS=30
AAC_KBPS=160                   # the sound of a video recording, kbit/s
MP3_KBPS=192                   # a sound-only recording, kbit/s
```

It applies from the next recording. The file is read, never run by a shell; a wrong value is
logged and replaced by the default. If the prototype's `~/.config/felvetel.conf` exists when
`hotrec.conf` is first written, its values are taken over once (and its encoder choice is dropped).

## Commands

`hotrec video-audio | video | audio | pause | stop | status | setup | autostart | shortcuts ... | indicator`;
see `man hotrec`. Recordings are named `2026-10-29_103000_video-audio.mkv` (`_video`, `_audio.mp3`).

## Needs

`gpu-screen-recorder`, `ffmpeg` with MP3 support, `pactl`, `notify-send`, `gsettings`; for the dot:
PyGObject, GTK 3, an AppIndicator library, and the AppIndicator extension of GNOME Shell. Python
3.9 or newer, no other Python package. How the files are laid out for a package:
[docs/installation-layout.md](docs/installation-layout.md).

## Development

```
python3 -m pytest          # needs pytest; msgfmt/xgettext (gettext) for the catalog tests
ruff check . && ruff format --check .
tools/i18n.sh check        # catalogs, template and data templates agree
```

How it works: [docs/design.md](docs/design.md). Languages: [docs/translations.md](docs/translations.md).
What is measured and what is not: [docs/measurements.md](docs/measurements.md).

GPL-3.0-or-later, TrenSoft.
