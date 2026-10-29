# How Hotrec works

One command per key press, no daemon. `hotrec <mode>` is a short-lived process that looks at what
is running, acts, and leaves; the recorder it started keeps running on its own.

## State

`$XDG_RUNTIME_DIR/hotrec/` (else `/tmp/hotrec-<uid>`, made mode 0700 and refused if it is not a
directory of ours), files:

- `state.json`: `pid`, `started` (the start time of that pid from `/proc/<pid>/stat`), `mode`,
  `file`, `paused`. Written whole and renamed into place.
- `lock`: held (`flock`) for the length of a command, so two quick key presses cannot both start
  a recording: the second one finds the first one's recording and stops it.
- `recorder.log`, `indicator.log`: output of the recorder and of the dot (not followed through
  symlinks); `indicator.lock`: the one dot.

A recording is "running" only if the pid exists, is not a zombie, **and has the start time that was
written**. A pid that the kernel gave to another process is not the recorder, and is never signalled.
A state whose process is gone (the portal dialog was cancelled, the recorder crashed, reboot) is
removed and the next key starts a new recording.

## Modes

| Mode | Program | Pause | Stop |
|---|---|---|---|
| `video-audio`, `video` | `gpu-screen-recorder -w portal -restore-portal-session yes -f FPS -k h264 -encoder gpu -bm cbr -q KBPS [-a default_output -ac aac -ab KBPS] -o FILE` | SIGUSR2 (the recorder toggles) | SIGINT |
| `audio` | `ffmpeg -n -f pulse -i <default sink>.monitor -c:a libmp3lame -b:a KBPS FILE` | SIGSTOP / SIGCONT | SIGINT |

Starting: the recorder is a new session (`start_new_session`), its output goes to `recorder.log`.
If it is gone within 1.5 s the user gets a notification with the log path, and no state is written.
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
symbolic icon, the three start entries are usable and Pause and Stop are greyed; while a recording
runs it is the other way round. The lock makes a second dot, resident or not, exit at once.
GTK 3 and an AppIndicator library (Ayatana first, then the old one) are imported only here.

The top of the menu holds four grey lines, "Ctrl+Shift+F9 - Record screen and sound", read from
GNOME (`Shortcuts.bindings()`) when the dot starts, after the window below saved, and every
minute (`KEYS_REREAD_TICKS`); a shortcut without keys, or GNOME's settings missing, leaves its line
hidden. The resident dot has "Set keyboard shortcuts..." at the bottom.

## The shortcuts window

`hotrec/keys_window.py` (GTK 3, opened from the resident dot, one at a time): a row per shortcut, a
button with its keys; a click waits for the next key combination (the keyboard is grabbed for the
wait, so the keys the shell already owns, such as the shortcut being changed, reach the window),
Escape gives up. A bare letter is refused; the function keys may stand alone. Save calls
`Shortcuts.install(keys)`, the code of `hotrec setup`, with the new accelerators: a key of another
custom keybinding is a `ShortcutConflict` (compared as keys, not as text, so `<Control>f9` equals
`<Primary>F9`) and nothing is written; two of ours with the same keys are refused before GNOME is
touched. Shortcuts that are not installed yet show the default keys (Ctrl+Shift+F9 to F12), which
is what Save would set; `hotrec autostart` installs exactly these, so the first window shows them
as they are. At the bottom right: "0.1.2 by TrenSoft" (not translated), as in the settings window of
Slideshow Lock. There is no separate About window.

## Settings and languages

See `hotrec/config.py` and `docs/translations.md`. The log and `--help` are English.
