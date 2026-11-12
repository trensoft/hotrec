# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later
# Shared by build.sh and check.sh (sourced, runs as root in a container of the image under test).

# dnf with no questions asked
gate_dnf() { dnf -y "$@"; }

# The repositories of the image under test. On EL10 the image is CentOS Stream 10 and the gate adds
# EPEL 10 and CRB, the way the COPR chroot epel-10 has them: pyproject-rpm-macros, which the build
# needs, is in CRB, and ffmpeg-free, which Hotrec requires (/usr/bin/ffmpeg), is in EPEL.
gate_repos() {
    . /etc/os-release
    echo "gate: image is ${PRETTY_NAME:-unknown}"
    case " ${ID_LIKE:-} ${ID:-} " in
    *" rhel "* | *" centos "*)
        gate_dnf install dnf-plugins-core
        gate_dnf config-manager --set-enabled crb
        gate_dnf install epel-release
        ;;
    esac
}

# The COPR project trensoft/hotrec, for ONE package: gpu-screen-recorder, which Hotrec requires and
# which only that project has. Hotrec itself is not taken from there (includepkgs): the package under
# test is the one built from the tree in stage 1. $1 is the COPR chroot without the architecture
# (epel-10, fedora-43, ...); it is given, not read from the image, because the image of rawhide does
# not say "rawhide" in a way every release keeps.
gate_copr_repo() {
    local chroot=${1:?gate_copr_repo needs the COPR chroot}
    local base=https://download.copr.fedorainfracloud.org/results/trensoft/hotrec
    cat > /etc/yum.repos.d/gate-copr-gpu-screen-recorder.repo <<REPO
[gate-copr-gpu-screen-recorder]
name=trensoft/hotrec ($chroot), gpu-screen-recorder only
baseurl=$base/$chroot-x86_64/
includepkgs=gpu-screen-recorder
gpgcheck=1
gpgkey=$base/pubkey.gpg
repo_gpgcheck=0
enabled=1
REPO
    echo "gate: COPR repository for gpu-screen-recorder: $base/$chroot-x86_64/"
}
