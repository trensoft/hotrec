# gpu-screen-recorder: command line recorder only, built against the distribution FFmpeg.
# Modelled on the arabianq/gpu-screen-recorder-rpm spec (checked 2026-10-29), with these deliberate differences:
#   - no setcap and no gsr-kms-server (Hotrec records through the desktop portal, -w portal, which needs neither);
#   - no systemd user unit, no nvidia modprobe file, no plugin header, no example scripts;
#   - no Epoch (the arabianq package uses Epoch 2; with both COPRs enabled theirs wins);
#   - FFmpeg is requested by pkgconfig name, so ffmpeg-free-devel (Fedora, EPEL 10) and any other provider satisfy it.
Name:           gpu-screen-recorder
Version:        6.1.6
Release:        1%{?dist}
Summary:        Screen recorder for Linux with GPU hardware encoding (command line only)

# README.md: "licensed under GPL-3.0-only" (not "or later"). The binary also compiles in the NVIDIA
# headers external/NvFBC.h and external/nvEncodeAPI.h (MIT), the wayland protocol XML of
# protocol/ (MIT) and external/sj.h (public domain; stb_image_write.h is MIT or public domain).
License:        GPL-3.0-only AND MIT AND LicenseRef-Fedora-Public-Domain
URL:            https://git.dec05eba.com/gpu-screen-recorder/about/
# The tarball has no top directory and is identical to the git tag %{version} (checked: 099a55b).
# Its sha256 is pinned in gpu-screen-recorder.sha256, which .copr/Makefile verifies after the download.
Source0:        https://dec05eba.com/snapshot/%{name}.git.%{version}.tar.gz

BuildRequires:  gcc
BuildRequires:  meson
BuildRequires:  pkgconfig(libavcodec)
BuildRequires:  pkgconfig(libavfilter)
BuildRequires:  pkgconfig(libavformat)
BuildRequires:  pkgconfig(libavutil)
BuildRequires:  pkgconfig(libswresample)
BuildRequires:  pkgconfig(libva)
BuildRequires:  pkgconfig(libva-drm)
BuildRequires:  pkgconfig(libdrm)
BuildRequires:  pkgconfig(libcap)
BuildRequires:  pkgconfig(libpulse)
BuildRequires:  pkgconfig(libpipewire-0.3)
BuildRequires:  pkgconfig(libspa-0.2)
BuildRequires:  pkgconfig(dbus-1)
BuildRequires:  pkgconfig(wayland-client)
BuildRequires:  pkgconfig(wayland-egl)
BuildRequires:  pkgconfig(wayland-scanner)
BuildRequires:  pkgconfig(x11)
BuildRequires:  pkgconfig(xcomposite)
BuildRequires:  pkgconfig(xdamage)
BuildRequires:  pkgconfig(xfixes)
BuildRequires:  pkgconfig(xrandr)
BuildRequires:  vulkan-headers

%description
GPU Screen Recorder records the screen with the hardware video encoder of the GPU (NVENC, VA-API,
Vulkan) and very little CPU use. This package has the command line recorder (gpu-screen-recorder)
and its control tool (gsr-cli) only, linked against the FFmpeg libraries of the distribution.

Screen capture on Wayland goes through the desktop portal (-w portal). The privileged helper for
direct monitor capture (gsr-kms-server) is not packaged. The software encoder needs libx264, which
the distribution FFmpeg does not have, so "-encoder cpu" with H.264 is not available.

%prep
%autosetup -c

%build
%meson \
    -Dsystemd=false \
    -Dcapabilities=false \
    -Dnvidia_suspend_fix=false \
    -Dplugin_examples=false \
    -Dffmpeg_static=false \
    -Dportal=true \
    -Dapp_audio=true
%meson_build

%install
%meson_install
# Built by the upstream build system whatever the options; not part of this package.
rm -f  %{buildroot}%{_bindir}/gsr-kms-server
rm -f  %{buildroot}%{_mandir}/man1/gsr-kms-server.1*
rm -rf %{buildroot}%{_includedir}/gsr
rm -rf %{buildroot}%{_datadir}/%{name}

%check
# Upstream has no test suite; start the binary and the control tool once.
%{buildroot}%{_bindir}/gpu-screen-recorder --version | grep -Fx '%{version}'

%files
%license LICENSE
%doc README.md
%{_bindir}/gpu-screen-recorder
%{_bindir}/gsr-cli
%{_mandir}/man1/gpu-screen-recorder.1*
%{_mandir}/man1/gsr-cli.1*

%changelog
* Thu Oct 29 2026 TrenSoft <143960729+trensoft@users.noreply.github.com> - 6.1.6-1
- First COPR package for trensoft/hotrec: 6.1.6, command line only, distribution FFmpeg, no setcap, no KMS server
