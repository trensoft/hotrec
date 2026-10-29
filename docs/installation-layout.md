# Installation layout (for the package)

The RPM specs are in `packaging/fedora/` and the COPR source-RPM builder in `.copr/Makefile`. This is what the tree offers them.

## Python part

`pyproject.toml` (setuptools): package `hotrec`, console script `hotrec = hotrec.cli:main`, no
Python dependencies (PyGObject comes from the distribution). `%pyproject_install` gives
`/usr/bin/hotrec` and `<sitelib>/hotrec/`. Python 3.9 or newer.

## Data part: `make install-data DESTDIR=%{buildroot} PREFIX=/usr`

| File | From |
|---|---|
| `/usr/share/applications/io.github.trensoft.hotrec.desktop` | `data/*.desktop.in`, translated |
| `/usr/share/metainfo/io.github.trensoft.hotrec.metainfo.xml` | `data/*.metainfo.xml.in`, translated |
| `/usr/share/icons/hicolor/scalable/apps/io.github.trensoft.hotrec.svg` | application icon |
| `/usr/share/icons/hicolor/symbolic/apps/io.github.trensoft.hotrec-symbolic.svg` | symbolic icon |
| `/usr/share/icons/hicolor/scalable/status/io.github.trensoft.hotrec-recording.svg` | red dot (lit half of the blink) |
| `/usr/share/icons/hicolor/scalable/status/io.github.trensoft.hotrec-recording-off.svg` | dark red ring (dark half of the blink) |
| `/usr/share/icons/hicolor/scalable/status/io.github.trensoft.hotrec-paused.svg` | yellow dot |
| `/usr/share/gnome-shell/extensions/hotrec-dot@trensoft.github.io/{metadata.json,extension.js,logic.js}` | the Shell extension, `gnome-shell/`; in the subpackage `hotrec-gnome-shell-extension` |
| `/usr/share/locale/<lang>/LC_MESSAGES/io.github.trensoft.hotrec.mo` x 40 | `po/*.po` (`po/LINGUAS`) |
| `/usr/share/man/man1/hotrec.1` | `packaging/man/hotrec.1` |
| `/etc/xdg/autostart/io.github.trensoft.hotrec-autostart.desktop` | `data/*-autostart.desktop` (`SYSCONFDIR`, default `/etc`; `%config(noreplace)`) |
| `%license LICENSE` | |

The target needs `make`, `msgfmt` (gettext) at build time; all files are mode 0644. It does not
touch icon caches or the desktop database (the package's scriptlets do that). Hotrec has no scriptlet
that sets keys: they are per user, and the autostart entry above does it at the user's login.

## Runtime, as a proposal for `Requires:`

Names are the Fedora ones and are **not checked against EPEL 10**:

- `gpu-screen-recorder` (command on the PATH, built against the system FFmpeg; portal mode needs
  no capabilities, so `setcap`/`gsr-kms-server` are not needed)
- `ffmpeg` (or `ffmpeg-free`) with `libmp3lame`, `pulseaudio-utils` or `pipewire-utils` (`pactl`),
  `libnotify` (`notify-send`), `glib2` (`gsettings`)
- the dot: `python3-gobject`, `gtk3`, `libayatana-appindicator-gtk3` (or `libappindicator-gtk3`);
  GNOME Shell needs its AppIndicator extension (`gnome-shell-extension-appindicator`) to show it:
  a Recommends/doc note, not a hard Requires
- optional: `xdg-user-dirs` (the default folder follows the Videos folder)
- optional: `intel-media-driver` (VA-API driver of Intel graphics, RPM Fusion nonfree; `Recommends:`, so a repository without it does not fail the install)

The program never calls Flatpak, and there is no software encoder, because the Fedora FFmpeg has no software H.264
encoder to use.

## Version and CI

No CI workflow. Version `0.1.4` is in `pyproject.toml`,
`hotrec/__init__.py`, the metainfo release and the manual page (`tests/test_packaging.py` keeps
them equal).
