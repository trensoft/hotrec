%global appid io.github.trensoft.hotrec

Name:           hotrec
Version:        0.1.5
Release:        1%{?dist}
Summary:        Screen and audio recorder for GNOME on Wayland, with global keys and a tray indicator
# The LICENSE file is the GPL-3.0 text; every .py carries SPDX-License-Identifier: GPL-3.0-or-later.
# gpu-screen-recorder (GPL-3.0-only) is a separate package that Hotrec only runs as a command; no code is taken from it.
License:        GPL-3.0-or-later
URL:            https://github.com/trensoft/hotrec
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch

BuildRequires:  python3-devel
# EL10: pyproject-rpm-macros is in CRB (the COPR epel-10 chroot has it enabled)
BuildRequires:  pyproject-rpm-macros
BuildRequires:  make
BuildRequires:  gettext
BuildRequires:  desktop-file-utils
BuildRequires:  libappstream-glib

# The recorder. Version pinned from below: the options Hotrec passes (-w portal, -restore-portal-session,
# SIGUSR2 pause) are those of 6.1.x. Comes from the same COPR project (trensoft/hotrec).
Requires:       gpu-screen-recorder >= 6.1.6
# Audio-only mode: any ffmpeg with libmp3lame. ffmpeg-free has it (libavcodec-free Requires libmp3lame.so.0);
# the file dependency also accepts the RPM Fusion ffmpeg. On EL10 ffmpeg-free is in EPEL 10.
Requires:       /usr/bin/ffmpeg
# Tray indicator and desktop helpers. python3-gobject is in AppStream on EL10.
Requires:       python3-gobject
Requires:       gtk3
# indicator.py loads the AyatanaAppIndicator3 typelib first, AppIndicator3 only as a fallback
Requires:       libayatana-appindicator-gtk3
Requires:       libnotify
# pactl (the prototype calls "pactl get-default-sink"); pipewire-utils has no pactl
Requires:       pulseaudio-utils
Requires:       glib2
Requires:       hicolor-icon-theme
# No procps-ng: the program calls no pgrep/pkill. No scriptlet sets the shortcuts: they belong to each user, so the autostart
# entry below runs "hotrec autostart" at the user's login, which sets them once (per user) and keeps the tray indicator.
# xdg-user-dirs: the default folder follows the Videos folder
Recommends:     xdg-user-dirs
# The GNOME tray needs the AppIndicator extension (Fedora and EPEL 10 have it), the screen cast dialog the
# GNOME portal. Recommended, not required, so a minimal install still works.
Recommends:     gnome-shell-extension-appindicator
Recommends:     xdg-desktop-portal-gnome
# Intel graphics encode H.264 through VA-API, and the driver for it (iHD, from RPM Fusion nonfree) is not in
# the base repositories: without it gpu-screen-recorder stops at "vaInitialize failed". Only Recommends: a weak
# dependency that dnf skips when no enabled repository has the package (EPEL 10 alone does not), so the install
# and the build never fail on it. Hotrec says in a notification when the driver is what is missing.
Recommends:     intel-media-driver
# The dot over a fullscreen video (a GNOME Shell extension, below). Recommended, not required: the tray dot works
# without it, and a minimal or non-GNOME install does not need it.
Recommends:     %{name}-gnome-shell-extension = %{version}-%{release}

%description
Hotrec records the screen with sound, only the screen, or only the sound, from a global key
(Ctrl+Shift+F9, F10, F11; F12 pauses), on GNOME under Wayland. The same key stops and saves. A red dot
in the top bar shows the recording, a yellow one the pause. Video is recorded by gpu-screen-recorder
through the screen cast portal, with the hardware encoder of the GPU.

%package gnome-shell-extension
Summary:        GNOME Shell extension for Hotrec: the recording dot above a fullscreen video
BuildArch:      noarch
Requires:       %{name} = %{version}-%{release}
# Extensions 47, 48 and 49 are declared in its metadata.json; EL10 has GNOME Shell 47
Requires:       gnome-shell >= 47

%description gnome-shell-extension
While Hotrec records, this GNOME Shell extension draws a blinking red dot in the top right corner, above
everything, also a fullscreen video where the top bar (and its tray dot) is out of sight; a yellow dot
that does not blink shows a pause. It reads only the state file Hotrec keeps while it records. "hotrec
autostart" switches it on once per user at login and says so in a notification; the Extensions app turns
it off, and it is not turned on again.

%generate_buildrequires
%pyproject_buildrequires

%prep
%autosetup

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files hotrec
make install-data DESTDIR=%{buildroot} PREFIX=%{_prefix} SYSCONFDIR=%{_sysconfdir}
%find_lang %{appid}

%check
%pyproject_check_import
desktop-file-validate %{buildroot}%{_datadir}/applications/%{appid}.desktop
desktop-file-validate %{buildroot}%{_sysconfdir}/xdg/autostart/%{appid}-autostart.desktop
appstream-util validate-relax --nonet %{buildroot}%{_datadir}/metainfo/%{appid}.metainfo.xml
test -x %{buildroot}%{_bindir}/hotrec

# No icon-cache or desktop-database scriptlets: Fedora and EL10 do this with file triggers (gtk-update-icon-cache,
# desktop-file-utils, appstream).

%files -f %{pyproject_files} -f %{appid}.lang
%license LICENSE
%doc README.md
%{_bindir}/hotrec
%config(noreplace) %{_sysconfdir}/xdg/autostart/%{appid}-autostart.desktop
%{_datadir}/applications/%{appid}.desktop
%{_datadir}/metainfo/%{appid}.metainfo.xml
%{_datadir}/icons/hicolor/scalable/apps/%{appid}.svg
%{_datadir}/icons/hicolor/symbolic/apps/%{appid}-symbolic.svg
%{_datadir}/icons/hicolor/scalable/status/%{appid}-recording.svg
%{_datadir}/icons/hicolor/scalable/status/%{appid}-recording-off.svg
%{_datadir}/icons/hicolor/scalable/status/%{appid}-paused.svg
%{_mandir}/man1/hotrec.1*

%files gnome-shell-extension
%license LICENSE
%{_datadir}/gnome-shell/extensions/hotrec-dot@trensoft.github.io/

%changelog
* Thu Oct 29 2026 TrenSoft <143960729+trensoft@users.noreply.github.com> - 0.1.5-1
- New: recording an area of the screen. "hotrec region-video-audio" (Ctrl+Shift+F7, with sound) and
  "hotrec region-video" (Ctrl+Shift+F8, screen only) dim the screen, the user drags the area with the mouse
  (own GTK 3 window on every monitor; Esc or the right button cancels). The portal still records the whole
  monitor; when the recording stops the area is cut out without encoding the video again (ffmpeg -c copy
  with the h264_metadata bitstream filter rewrites the cropping values of the stream), so no video encoder
  is needed. The left edge moves to a multiple of 64 pixels, the others to 2 pixels. If the cut fails the
  whole screen is kept and a notification says so
- The two keys are in the shortcuts window and can be changed there. "hotrec autostart" adds them for people
  who set the first four up with an older version, once, and touches no entry that is there
- F9 to F12 are unchanged
* Thu Oct 29 2026 TrenSoft <143960729+trensoft@users.noreply.github.com> - 0.1.4-1
- New subpackage hotrec-gnome-shell-extension (Recommends: of hotrec): a GNOME Shell extension, GNOME 47-49,
  that shows a blinking red dot above everything, also a fullscreen video, while Hotrec records (a steady yellow
  one while paused). It reads the state file Hotrec keeps; nothing runs while nothing records
- "hotrec autostart" switches the extension on once per user (gsettings enabled-extensions) when the package is
  installed, and says in a notification that a log out and in may be needed (not when the Shell already knows
  the extension: then it is on at once); an extension the user turned off is
  left off. The tray dot stays: it is the fallback where the extension cannot be used

* Thu Oct 29 2026 TrenSoft <143960729+trensoft@users.noreply.github.com> - 0.1.3-1
- Recommends: intel-media-driver (the VA-API driver of Intel graphics, RPM Fusion nonfree; weak, never required)
- When the video encoder does not start, or the recorder ends by itself because of it, a desktop notification
  says what is missing (the VA-API driver, intel-media-driver) instead of only writing to the log
- The red dot in the top bar blinks while a recording runs (a new icon, hotrec-recording-off, is its dark half);
  the yellow one of a paused recording stays steady
- The settings window has a folder for video recordings and one for sound-only recordings (VIDEO_FOLDER and
  AUDIO_FOLDER); a folder that cannot be used falls back to FOLDER

* Thu Oct 29 2026 TrenSoft <143960729+trensoft@users.noreply.github.com> - 0.1.2-1
- The menu of the tray indicator lists the keyboard shortcuts as GNOME has them (grey, not clickable) and has
  "Set keyboard shortcuts...": a small window to choose the four key combinations, saved into the GNOME custom
  keybindings by the same code as "hotrec setup" (a key of another program is never overwritten)

* Thu Oct 29 2026 TrenSoft <143960729+trensoft@users.noreply.github.com> - 0.1.1-1
- Autostart entry in /etc/xdg/autostart: "hotrec autostart" sets the keyboard shortcuts once per user at login and keeps
  the tray indicator running (one instance); the prototype's felvetel shortcuts are replaced by the Hotrec ones

* Thu Oct 29 2026 TrenSoft <143960729+trensoft@users.noreply.github.com> - 0.1.0-1
- Packaging for trensoft/hotrec: Python part by pyproject macros, data part by make install-data
