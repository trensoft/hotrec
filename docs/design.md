# How Hotrec works

One command per key press, no daemon. `hotrec <mode>` is a short-lived process that looks at what
is running, acts, and leaves; the recorder it started keeps running on its own.

## State

`$XDG_RUNTIME_DIR/hotrec/` (else `/tmp/hotrec-<uid>`, made mode 0700 and refused if it is not a
directory of ours), files:

- `state.json`: `pid`, `started` (the start time of that pid from `/proc/<pid>/stat`), `mode`,
  `file`, `paused`. Written whole and renamed into place.
- `lock`: held (`flock`) for the length of a command, so two quick key presses cannot both start
  a recording: the second one finds the first one's recording and stops it. At a stop it is held
  until the recorder has ended and the state is cleared (`Recorder._halt`), and released before
  the area is cropped (`Recorder._finish`): the crop can take minutes for a long recording, and a
  key pressed meanwhile (a new recording, pause) must not wait for it.
- `recorder.log`, `indicator.log`: output of the recorder and of the dot (not followed through
  symlinks); `indicator.lock`: the one dot.

A recording is "running" only if the pid exists, is not a zombie, **and has the start time that was
written**. A pid that the kernel gave to another process is not the recorder, and is never signalled.
A state whose process is gone (the portal dialog was cancelled, the recorder crashed, reboot) is
removed and the next key starts a new recording.

## Modes

| Mode | Program | Pause | Stop |
|---|---|---|---|
| `video-audio`, `video` | `gpu-screen-recorder -w portal -restore-portal-session yes -f FPS -k h264|hevc -encoder gpu -bm cbr -q KBPS [-a default_output -ac aac -ab KBPS] -o FILE` | SIGUSR2 (the recorder toggles) | SIGINT |
| `region-video-audio`, `region-video` | the same `gpu-screen-recorder` command as `video-audio` / `video` (the whole monitor, but always `-k h264`: the cut below works on H.264 headers), after the area was drawn; at the stop `ffmpeg -c copy -bsf:v h264_metadata=crop_*` rewrites the area into the file (see "The area") | SIGUSR2 | SIGINT, then the cut |
| `audio` | `ffmpeg -n -f pulse -i <default sink>.monitor -c:a libmp3lame\|aac\|libopus -b:a KBPS FILE` (`.mp3`, `.aac`, `.opus`) | SIGSTOP / SIGCONT | SIGINT |

Starting: the recorder is a new session (`start_new_session`), its output goes to `recorder.log`.
If it is gone within 1.5 s the user gets a notification with the log path, and no state is written.
When the end of the log shows an encoder failure on an error line (one that starts with `gsr error:`,
`gsr warning:` or `libva error:`; the `libva info:` lines of a working VA-API do not count) (`vaInitialize failed` and other VA-API words: the VA-API
driver is missing, with the package named, `intel-media-driver`; `nvenc`, `cuda`, `encoder`: a general
encoder message) the notification says that instead. With the portal the encoder starts only after the
screen is chosen, so the recorder can also end well after the start: `read_state` finds the pid gone,
removes the state, and, for a video recording whose log shows an encoder failure, sends "The recording
stopped" with the same text (a cancelled screen choice and sound recordings end quietly, as before).

Folders: `FOLDER` is the default; `VIDEO_FOLDER` and `AUDIO_FOLDER` (set in the Settings window or by hand)
override it per kind. A chosen folder is used when it can be made and written (an unplugged drive cannot);
else the recording goes to `FOLDER` and the log says why.
A missing program is named ("gpu-screen-recorder is not installed"). The sound-only mode needs the
default sink from `pactl get-default-sink`.

Stopping: a paused recording is sent SIGCONT first (a stopped process cannot see SIGINT), then
SIGINT; the recorder writes the end of the file. After 20 s SIGTERM, after 5 s more SIGKILL, and the
notification says the recording may be incomplete. A stop that leaves no file is reported the same
way, never as "saved".

The container is `mkv` by default: a recording that is cut short (power loss, a kill) still plays;
`mp4` written by an interrupted recorder does not on the FFmpeg 7.1 of EPEL 10.

## Shortcuts

`hotrec shortcuts install` writes four custom keybindings under
`/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/hotrec-<mode>/`
(`name`, `command`, `binding`) with `gsettings`, and adds the paths to the list key. It reads the
list first and keeps the entries of others, refuses when another custom entry uses one of the keys
(nothing is changed), writes the list last, and does nothing the second time. Keys of GNOME's own
(non-custom) shortcuts are not checked.

The prototype's keys are replaced: a custom entry counts as one when its **command** is
`felvetel.sh` (or `felvetel`) followed by `kepeshang`, `kep`, `hang` or `szunet` as a whole word,
or is `felvetel-<that word>` (`is_legacy_command`, tested with the commands in
`tests/test_shortcuts.py`). The entry's name and dconf path are not looked at: another program's
entry that is merely called `felvetel-...` stays, and still counts for the conflict check. The
prototype entries are taken out of the list in the same write that adds ours and their keys are
reset afterwards, so a failed write leaves them as they were; the key one of them held is not a
conflict.

## Autostart

`/etc/xdg/autostart/io.github.trensoft.hotrec-autostart.desktop` (GNOME only, hidden from the
menus) runs `hotrec autostart` at every login. The first time it runs the same code as
`hotrec setup` (shortcuts and the notification) and writes
`$XDG_STATE_HOME/hotrec/shortcuts-installed` (`~/.local/state/hotrec/` by default). The marker is
written when the shortcuts are set and when another program holds one of the keys (the person has
to decide; a notification at every login would nag). Another failure (gsettings not ready yet)
writes no marker, so the next login tries again. Either way it then becomes the dot: it runs
`indicator.run(resident=True)`.

## The dot

`hotrec indicator` (started by a recording, one at a time) shows `...-recording` or `...-paused`
(red or yellow) and a menu; it polls the state twice a second and quits when nothing records.
The resident one (`hotrec autostart`) does not quit: while nothing records it shows the Hotrec
symbolic icon, the five start entries are usable and Pause and Stop are greyed; while a recording
runs it is the other way round. The lock makes a second dot, resident or not, exit at once.
GTK 3 and an AppIndicator library (Ayatana first, then the old one) are imported only here.

The resident menu, in this order: the five ways to start (screen and sound, screen, sound, area and
sound, area), Pause/Resume, Stop and save, a separator, Settings..., About, Quit. Quit stops and saves a recording that runs
(`Recorder.stop()`, in a thread off the GTK thread, as Stop and save does), then quits the GTK loop;
if the recording is still there afterwards the dot stays and Quit works again. Autostart is not
touched. Each command line carries its
keys, "Record screen and sound (Ctrl+Shift+F9)", read from GNOME (`Shortcuts.bindings()`) when the dot
starts, right after the Settings window changed a key, and every minute (`KEYS_REREAD_TICKS`); a
shortcut without keys, or GNOME's settings missing, leaves the line as the bare name. Pause keeps its
keys when it turns into Resume. The dot of a single recording (not resident) has Pause and Stop only.
There is no separate list of the keys: the lines are the keys.

## The Settings window

`hotrec/settings_window.py` (GTK 3, opened from the resident dot, one at a time) holds every setting
of the program in one place; `hotrec/about_window.py` is the About window beside it (name, version,
the one-line description, Website and Report a problem as link buttons, the license id, Close; its
lines are Hotrec's own translated strings, not `Gtk.AboutDialog`'s).

Every control writes the moment it changes (`config.set_values` into `~/.config/hotrec.conf`, or for
a key `Shortcuts.install`); there is no Save. While the controls are set from the file nothing is
written (`applying`), and a write that fails is shown in the window (the error text, which names the
file) and the controls go back to what the file has, so the window never says what the file does not.

- *Keyboard shortcuts*: a row per shortcut, a button with its keys; a click waits for the next key
  combination (the keyboard is grabbed for the wait, so the keys the shell already owns, such as the
  shortcut being changed, reach the window), Escape gives up. A bare letter is refused; the function
  keys may stand alone. A new combination calls `Shortcuts.install(keys)`, the code of `hotrec setup`,
  with all six accelerators: a key of another custom keybinding is a `ShortcutConflict` (compared as
  keys, not as text, so `<Control>f9` equals `<Primary>F9`) and nothing is written; two of ours with
  the same keys are refused before GNOME is touched; either way the row goes back to its old keys.
  Shortcuts that are not installed yet show the default keys (Ctrl+Shift+F7 to F12), which is what
  the next change would set; `hotrec autostart` installs exactly these. The menu is told
  (`on_saved`) and shows the new keys at once.
- *Video*: `VIDEO_CODEC` as two radio buttons (H.264, H.265), `VIDEO_KBPS` a slider over
  `VIDEO_BITRATE_STEPS` (25 steps from 500 to 100000 kbit/s, each 1.14 to 1.33 times the one before,
  so it is exponential; 12000, the default, is a step), `FPS` a slider over 10 to 144, `CONTAINER`
  two radio buttons. A value in the file that is not a step is shown by the nearest step (by ratio),
  with its real number as the text, and stays until the slider is moved.
- *H.265 is offered only if the card can encode it* (`hotrec/codecs.py`): the recorder is asked
  (`gpu-screen-recorder --info`, then `--list-supported-video-codecs`; 8 s deadline, once per process)
  and only a codec it names counts; a missing program, a failure, a timeout and an answer that is
  not understood all mean "not offered". Then the H.265 button is greyed and the line "H.265 is not
  available: the graphics card cannot encode it." shows; when H.265 is chosen the line about extra
  codecs for Windows and browsers shows. `VIDEO_CODEC=h265` in the file works regardless.
- *Sound*: `AUDIO_CODEC` (MP3, AAC, Opus) is the codec of a **sound-only** recording only; the sound
  of a video is always AAC (`-ac aac`). Its note ("Applies only to sound-only recordings...") shows
  whenever the codec is not AAC. `AAC_KBPS` (inside a video) and `MP3_KBPS` (sound-only, whatever the
  codec; the key keeps the old name so existing files keep working) are sliders over
  `SOUND_BITRATE_STEPS`, 32 to 320 in 10 fixed steps.
- *Folders*: a label with the folder and "Choose...", which opens the portal's folder chooser;
  choosing `FOLDER` again unsets the key.
- *Reset to defaults*: asks "Reset every setting to its default value?", then removes every key
  from the file (so each has its default) and installs the six default keys.
- At the bottom right: "0.1.7 by TrenSoft" (the version, not translated).

**An area recording is always H.264** (`video_command(..., area=True)`, with a log warning when the
file says otherwise): the area is cut out by rewriting H.264 headers (`h264_metadata`). The HEVC
counterpart (`hevc_metadata`, and the coded-size rounding of an H.265 stream) is not measured, so
it is not guessed.

What is not in the window, on purpose: loudness normalising, a mono/stereo choice, presets, an
"advanced" mode (decisions of the owner, 2026-10-31).

## The area (0.1.5)

`region-video-audio` (Ctrl+Shift+F7) and `region-video` (Ctrl+Shift+F8). With nothing recording, the
key runs `hotrec select-region` as a process of its own (`selector.py`, GTK 3 is loaded only there):
on every monitor a transparent fullscreen window dims the screen; a drag with the left button draws
the area, the release chooses it, Escape or the right button gives up (exit status 3). The window prints
the area as JSON, as **fractions of the monitor it was drawn on** plus the monitor's width/height
(`region.Region`). No lock is held while the window is open (`select.lock` refuses a second window); the
state is read again afterwards, and a recording that started meanwhile is left alone. The area is kept in
`state.json` (`region`, `[left, top, right, bottom, aspect]`).

The portal records the whole monitor, as for `video`. At the stop, after the recorder ended cleanly,
`Recorder._cut_out` reads the size of the file (`ffmpeg -i`), turns the fractions into pixels
(`region.crop_for`) and runs `ffmpeg -c copy -bsf:v h264_metadata=crop_left=..:crop_right=..:crop_top=..:crop_bottom=..`
into a temporary file next to the recording, which replaces it only if ffmpeg succeeded and wrote
something. Nothing is encoded again, so there is no encoder to be missing and it takes seconds.

**This is a crop of the view, not a redaction, and the documentation says so** (README, man page,
spec changelog, and the notification after an area recording, whose body says the rest of the screen
stays in the file). The whole picture is still in the file: the cropping values are metadata, one
`ffmpeg -c copy -bsf:v h264_metadata=crop_left=0:...` brings the whole screen back (measured by the
reviewer: 1920x1088 again, the file size does not shrink), and some players and editors ignore the
cropping. Taking the rest of the picture away needs encoding again, which needs an encoder (the
Fedora ffmpeg has no software H.264 encoder) and a decision about which one; it is not done in
0.1.5 (backlog). The
cropping values are counted against the coded size (visible size rounded up to 16) in steps of 2 pixels;
ffmpeg based players cut the left edge exactly only at a multiple of 64 pixels, so the left edge moves
left to such a column. When the file does not have the shape of the monitor the area was drawn on
(2% tolerance: the portal recorded another monitor), or ffmpeg fails, the whole screen stays and the
notification says so.

Known limit: the area is kept as fractions and the shape of the monitor, not as *which* monitor. With
two monitors of the same shape the portal can record the other one, the shape check passes, and the
area is cut from the wrong monitor's picture with no warning. It is in the README and the man page; a
fix needs the monitor the selector window was on to be stored and compared with the one the portal
records (not measured how, the portal does not necessarily say).

Existing users: `hotrec autostart` runs `Shortcuts.add_missing()` once (marker
`shortcuts-regions-added`), which adds only the entries that are not in the list, with their default keys,
and leaves out a key another custom keybinding (or one of our entries) already has; nothing that is there
is changed. Only the two area entries (`ADDED_IN_0_1_5`) are ever added: an F9-F12 entry that a person
took out (`hotrec shortcuts remove`, or by hand) is not put back.

## The dot over a fullscreen video (0.1.4)

`gnome-shell/hotrec-dot@trensoft.github.io/` (GNOME Shell 47-49, ES module extension; subpackage
`hotrec-gnome-shell-extension`, `Recommends:` of the main package). `extension.js` puts a `St.Widget` in
`Main.layoutManager.addTopChrome` with `trackFullscreen: false`, `affectsInputRegion: false`, so it is
above a fullscreen window and never takes a click; `logic.js` is the decision code without any GNOME API
(tested with plain node, `tests/js/`, against a fake desktop).

The signal is the state file Hotrec already keeps, `$XDG_RUNTIME_DIR/hotrec/state.json` (`pid`, `started`,
`mode`, `file`, `paused`); no D-Bus name and no second file, so there is one source of truth and nothing
for Hotrec to forget to write. The extension watches the directory with `Gio.FileMonitor` (the runtime
directory until Hotrec has made its own). A recording counts only when `/proc/<pid>/stat` has the same start
time as `started` and the process is not a zombie, the check `Recorder.is_alive` makes, so the state file a
crashed recorder leaves behind does not leave a dot: while a dot is shown a 500 ms timer blinks it and runs
that check again; with no dot there is no timer. Red and blinking = recording (also sound only), steady
yellow = paused (gpu-screen-recorder writes no frames while paused), nothing otherwise.

Switching it on: `hotrec/shellext.py`, called by `hotrec autostart` after the shortcuts. If the package is
installed (`metadata.json` in a data directory) and the marker `dot-extension-offered` is not there, the
UUID is added to `org.gnome.shell enabled-extensions` unless it is already there or in
`disabled-extensions`, the marker is written and one notification says it; a running Shell loads a new
extension at the next login, which the notification says. An extension the user turns off later is not
turned on again. If `gsettings` fails nothing is written and the next login tries again.

**Direct scanout is off while the dot shows, and that has a side effect.** A fullscreen window that
mutter "unredirects" (direct scanout) bypasses the compositor, so the top chrome the dot lives in is
not painted above it: the dot would be missing exactly when it is wanted, over a fullscreen video.
While the dot shows, `extension.js` therefore keeps unredirect disabled (`global.compositor.
disable_unredirect()` on GNOME 48 and later, `Meta.disable_unredirect_for_display(global.display)` on
47) and gives it back when the dot goes (or the extension is turned off); the calls are counted by
mutter, so they pair exactly (`_unredirectHeld`). For the length of a recording, or a pause, a
fullscreen video or game is composited like any window instead of scanned out directly: somewhat more
GPU work and power, and the frame pacing of a fullscreen game can be less smooth. The recording
itself is not affected. If the call throws, the dot still shows, one warning is logged, and the call is
not repeated while the dot stays (`_unredirectFailed`; before this, `_show` retried and warned at every
blink, twice a second); the next appearance of the dot tries once more.

Not measured: a run in a real GNOME Shell, and whether the portal screen recording contains the dot (the
monitor stream is the whole stage, so it probably does). If it does, the tray dot is the fallback: turn the
extension off in the Extensions app.

## Settings and languages

See `hotrec/config.py` and `docs/translations.md`. The log and `--help` are English.
