# What is measured, and what is not (0.1.0)

## Measured here (a Linux container, Python 3.11, gettext 0.21, no display, no GPU)

- `python3 -m pytest`: the whole logic of the recorder (commands, state, stop/pause/kill ladder,
  stale and reused pids, two key presses at once), the settings file, the shortcuts (against a fake
  `gsettings`), the dot (against a stand-in for GTK and AppIndicator), the 40 catalogs, the install
  layout, the manual page and the launcher against the code.
- Real processes and real signals against stand-ins for `gpu-screen-recorder`, `ffmpeg`, `pactl`
  and `notify-send` (`tests/test_end_to_end.py`): start, pause (SIGUSR2; SIGSTOP/SIGCONT), stop with
  SIGINT, a recorder that fails at once, a missing program, `run.sh` building and using catalogs.
- `tools/i18n.sh check`: 40 catalogs compile with `msgfmt -c --check-format`, template and source
  agree, the launcher and metadata build with all 40 languages.
- `make install-data` into a build root: the file list of `docs/installation-layout.md`.
- Mutation checks of the recorder, shortcut and settings code: see the commit message of the
  hand-off for the list.

## NOT measured

- A real GNOME session: the custom keybindings written by `gsettings` and the keys firing in
  every window on Wayland; the launcher; the notifications.
- A real recording: `gpu-screen-recorder` 6.1.6 with these options on NVENC (the PC of the owner)
  or VA-API (the laptop), the portal dialog and its remembered session, the pause of a real
  recorder (SIGUSR2), 4K load, the audio of `-a default_output -ac aac -ab`. The arguments are the
  prototype's, carried over unchanged, not re-checked against the option list of the package that
  will be installed.
- `ffmpeg` recording the monitor of a real sound output, and what SIGSTOP does to the timeline of
  a real PulseAudio/PipeWire capture (the prototype did the same).
- The dot on a real desktop: GTK 3 and AppIndicator are not installed in the test environment;
  only the logic around them is tested, against a stand-in. Whether the AppIndicator extension
  shows the icon, and the icon theme lookup of the two icon names, is unchecked.
- The Shell extension (0.1.4) in a real GNOME Shell: it loads (GNOME 47-49), the dot shows above a
  fullscreen video, blinks, goes when the recording ends. Tested: `logic.js` and `extension.js` under
  node (`tests/js`) against a fake desktop that has the Shell, Gio and GLib calls the extension makes;
  the real signatures of `addTopChrome`, `Gio.FileMonitor` and `St.Widget` were not compared with the
  GNOME Shell 47 sources. Whether a portal screen recording contains the dot is not known (the monitor
  stream is the whole stage, so probably): then the extension is switched off and the tray dot stays.
  That `gsettings set org.gnome.shell enabled-extensions` makes a running Shell load a new extension
  without a login is not measured either (the notification says a login may be needed).
- The area (0.1.5): measured with an ffmpeg 7.0 binary, on synthetic H.264 files: the picture of
  `-c copy -bsf:v h264_metadata=crop_*` is bit for bit the one the `crop` filter gives (mkv, mp4,
  extradata and in-band SPS), and an unaligned left edge is widened by ffmpeg (hence the 64 pixels).
  **Not measured:** the GTK 3 area window on a real GNOME Wayland desktop (dimming, drag, Escape and
  right button, cursor, several monitors, scaling); the SPS of a real gpu-screen-recorder stream
  (NVENC / VA-API) cut and played; that the portal stream has the shape of the monitor; two monitors
  with the same shape (the wrong one would be cut); the packaging as an RPM.
- The packages: the names in `docs/installation-layout.md` are not checked against EPEL 10 or
  Fedora, and nothing was built as an RPM.
- Translations by a native speaker (none), RTL display of Arabic and Hebrew in a notification.
