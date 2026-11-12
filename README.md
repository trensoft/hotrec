# Hotrec

Screen and sound recorder for GNOME on Wayland, driven by keyboard shortcuts. Made for webinars,
where OBS cannot be started from the keyboard on Wayland unless its own window is in front: the
keys here are GNOME's own custom shortcuts, so they work in every window.

| Key | What it does |
|---|---|
| Ctrl+Shift+F9 | record the screen and the sound |
| Ctrl+Shift+F10 | record the screen only |
| Ctrl+Shift+F11 | record the sound only (MP3, or AAC or Opus in the settings) |
| Ctrl+Shift+F12 | pause, and resume |
| Ctrl+Shift+F7 | record an area of the screen, with the sound |
| Ctrl+Shift+F8 | record an area of the screen only |

The same key stops and saves the recording that runs (any of F7 to F11 does, whichever started
it). While a recording runs, a red blinking dot in the top bar shows it, a yellow steady one that it is paused;
its menu has Pause/Resume and Stop and save.

The dot that stays in the top bar after login has the menu of the program. Each command is one
line with its keys as GNOME has them now: **Record screen and sound (Ctrl+Shift+F9)**, **Record screen
only**, **Record sound only**, **Record area and sound**, **Record area only**, **Pause** (it turns
into **Resume**), **Stop and save**; then **Settings...**, **About** and, last, **Quit**. Quit stops and saves a running
recording first, then ends the dot (the next login starts it again).

**Settings** is one window with everything in it, and every control takes effect as you change it
(there is no Save button; "Reset to defaults" asks first, then puts every setting and the six keys
back):

- *Keyboard shortcuts*: a field for each shortcut. Click a field, press the new keys (Escape gives
  up; a letter alone is refused, a function key may stand alone). The window writes the GNOME custom
  keybindings with the same code as `hotrec shortcuts install`, so a key that another program's
  custom shortcut already uses is refused and said so, and nothing of other programs is overwritten.
- *Video*: the codec (H.264, or H.265 for about half the file size), the bit rate (a slider on an
  exponential scale, 500 kbit/s to 100 Mbit/s), the frame rate and the file format (MKV or MP4).
  **H.265 can be chosen only when the graphics card can encode it** (NVENC, or VA-API on Intel); the
  window asks `gpu-screen-recorder` and, if it does not say so, shows why it is greyed out. H.265
  videos may need an extra codec to play on Windows and in some browsers. **An area recording
  (F7, F8) is always H.264**, because the area is cut out by rewriting the H.264 headers.
- *Sound*: the codec of a **sound-only** recording (MP3, AAC or Opus; the sound of a video is always
  AAC) and two bit rates on fixed steps from 32 to 320 kbit/s, one for the sound inside a video and
  one for a sound-only recording.
- *Folders*: where videos and where sound recordings are saved.

The version and the maker are at the bottom of the window.

**Recording an area** (F7, F8): the screen is dimmed on every monitor and the area is drawn with the
mouse (drag with the left button; Escape or the right button gives up). The portal still records the
whole monitor; when the recording stops, the picture is cropped to the area **without encoding the
video again**: `ffmpeg -c copy` with the `h264_metadata` bitstream filter rewrites the cropping values
in the H.264 headers, which takes seconds and needs no video encoder. The left edge of the area moves
left to a multiple of 64 pixels (players cut the left edge exactly only there), the other edges to 2
pixels.

**This crops the view, it does not black out the rest.** The whole picture of the monitor stays in the
file; only the instruction "show this part" is changed. Anyone who has the file can remove the cropping
with one ffmpeg command and get the whole screen back (other windows, notifications, a password
manager, a chat), and some players and editors ignore the cropping and show the whole screen at once.
Do not use the area to hide something from the person you send the file to. The notification after the
recording says so. Cutting the picture away for real (encoding it again) is not done in 0.1.5.

The area belongs to the monitor the portal records, which is the one you chose in the portal's
dialog, not necessarily the one you drew on. Hotrec only stores the area as fractions of the screen
(and the shape of the monitor), not which monitor it was. With two monitors of the same shape the
fractions are applied to whichever one the portal records, and the area can be the wrong part of the
picture, with no warning. If the shape differs, or ffmpeg fails, the whole screen stays in the file
and a notification says so. People who set the first four keys up with an older version get F7 and F8
added at the next login, by `hotrec autostart`, and nothing else of theirs is touched: a shortcut of
the first four that they took out is not put back.

The screen is recorded by `gpu-screen-recorder` (portal mode: the desktop asks which screen, once,
and remembers), encoded as H.264 (or H.265, if you chose it) by the graphics hardware (NVENC,
VA-API). The sound of the video is AAC; a sound-only recording is `ffmpeg` writing MP3 (or AAC or
Opus, as the settings say). There is no software encoder.

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
fullscreen. The subpackage `hotrec-gnome-shell-extension` (GNOME Shell 47-51; `hotrec` recommends it,
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

**What it costs: direct scanout is off while the dot shows.** A fullscreen window that GNOME's
compositor (mutter) "unredirects" is sent to the screen directly, past the compositor, and nothing
the Shell draws (the dot included) is painted above it. So while the dot shows, the extension asks
the compositor not to unredirect (`disable_unredirect`) and gives that back when the dot goes away,
so it is off only while a recording or a pause is on. The side effect is that a fullscreen video or
game is composited like any other window for that time: a little more GPU work and power, and the
frame pacing of a fullscreen game can be slightly less smooth. It does not touch the recording
itself. If the call fails (it is a different one on GNOME 47 and 48+) the dot still shows, the
extension logs one warning and tries again at the next recording, not twice a second.

From a checkout, without installing: `./run.sh shortcuts install --command "$PWD/run.sh"`.

## Settings

`~/.config/hotrec.conf`, written on the first run (`$XDG_CONFIG_HOME` is honoured):

```
FOLDER="$HOME/Videos/Hotrec"   # where recordings are saved
# VIDEO_FOLDER=                # not set: the FOLDER above (the Settings window sets these two)
# AUDIO_FOLDER=
CONTAINER=mkv                  # mkv (plays back even if cut short) or mp4
VIDEO_CODEC=h264               # h264 (plays everywhere) or h265 (half the size)
VIDEO_KBPS=12000               # video bit rate, kbit/s
FPS=30
AAC_KBPS=160                   # the sound of a video recording, kbit/s
AUDIO_CODEC=mp3                # a sound-only recording: mp3, aac or opus
MP3_KBPS=192                   # a sound-only recording, kbit/s, whatever its codec
```

The Settings window writes this file; you can also edit it by hand. `VIDEO_CODEC=h265` works from the
file even where the window does not offer H.265, and then the recorder reports the failure if the
card cannot encode it. `MP3_KBPS` keeps its name from the days when MP3 was the only codec of a
sound-only recording.

It applies from the next recording. The file is read, never run by a shell; a wrong value is
logged and replaced by the default. If the prototype's `~/.config/felvetel.conf` exists when
`hotrec.conf` is first written, its values are taken over once (and its encoder choice is dropped).

## Commands

`hotrec video-audio | video | audio | region-video-audio | region-video | select-region | pause | stop | status | setup | autostart | shortcuts ... | indicator`;
see `man hotrec`. Recordings are named `2026-10-29_103000_video-audio.mkv` (`_video`, `_audio.mp3`; `.aac` or `.opus` for those codecs).

## Needs

`gpu-screen-recorder`, `ffmpeg` with MP3 support (and Opus, if you choose it), `pactl`, `notify-send`, `gsettings`; for the dot:
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
