%global appid io.github.trensoft.hotrec

Name:           hotrec
Version:        0.1.0
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
# No procps-ng: the program calls no pgrep/pkill. Shortcuts are set by the user (hotrec shortcuts install), not by a scriptlet.
# xdg-user-dirs: the default folder follows the Videos folder
Recommends:     xdg-user-dirs
# The GNOME tray needs the AppIndicator extension (Fedora and EPEL 10 have it), the screen cast dialog the
# GNOME portal. Recommended, not required, so a minimal install still works.
Recommends:     gnome-shell-extension-appindicator
Recommends:     xdg-desktop-portal-gnome

%description
Hotrec records the screen with sound, only the screen, or only the sound, from a global key
(Ctrl+Shift+F9, F10, F11; F12 pauses), on GNOME under Wayland. The same key stops and saves. A red dot
in the top bar shows the recording, a yellow one the pause. Video is recorded by gpu-screen-recorder
through the screen cast portal, with the hardware encoder of the GPU.

%generate_buildrequires
%pyproject_buildrequires

%prep
%autosetup

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files hotrec
make install-data DESTDIR=%{buildroot} PREFIX=%{_prefix}
%find_lang %{appid}

%check
%pyproject_check_import
desktop-file-validate %{buildroot}%{_datadir}/applications/%{appid}.desktop
appstream-util validate-relax --nonet %{buildroot}%{_datadir}/metainfo/%{appid}.metainfo.xml
test -x %{buildroot}%{_bindir}/hotrec

# No icon-cache or desktop-database scriptlets: Fedora and EL10 do this with file triggers (gtk-update-icon-cache,
# desktop-file-utils, appstream).

%files -f %{pyproject_files} -f %{appid}.lang
%license LICENSE
%doc README.md
%{_datadir}/applications/%{appid}.desktop
%{_datadir}/metainfo/%{appid}.metainfo.xml
%{_datadir}/icons/hicolor/scalable/apps/%{appid}.svg
%{_datadir}/icons/hicolor/symbolic/apps/%{appid}-symbolic.svg
%{_datadir}/icons/hicolor/scalable/status/%{appid}-recording.svg
%{_datadir}/icons/hicolor/scalable/status/%{appid}-paused.svg
%{_mandir}/man1/hotrec.1*

%changelog
* Thu Oct 29 2026 TrenSoft <143960729+trensoft@users.noreply.github.com> - 0.1.0-1
- Packaging for trensoft/hotrec: Python part by pyproject macros, data part by make install-data
