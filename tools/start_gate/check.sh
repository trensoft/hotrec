#!/bin/bash
# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later
# Start gate, stage 2: install the RPMs into a clean container and start the program from the
# installed copy. Runs as root in a fresh container of the image under test, which has neither the
# source tree nor the build tools of stage 1.
#   /gate this directory
#   /out  the output of build.sh (read only is enough)
#   START_GATE_CHROOT  the COPR chroot of the image (gpu-screen-recorder comes from that chroot)
# probe_installed.py: the installed version is the RPM's, the modules import, the toolkit loads, the
# command line answers, a translation catalog is found, the programs Hotrec runs are there.
# probe_session.py: the real `hotrec autostart` in a headless GNOME Shell session: the shortcuts are
# set, the Shell takes the extension, the dot is registered, the menu is there, Quit ends it with 0.
# The probes both run; the exit status is 1 if one failed. The last line, "START-GATE RESULT ...",
# is the summary.
set -euo pipefail
. /gate/common.sh

chroot=${START_GATE_CHROOT:?START_GATE_CHROOT is not set}
gate_repos
gate_copr_repo "$chroot"
shopt -s nullglob
mains=(/out/rpm/hotrec-[0-9]*.noarch.rpm)
exts=(/out/rpm/hotrec-gnome-shell-extension-[0-9]*.noarch.rpm)
[ "${#mains[@]}" -eq 1 ] || { echo "START-GATE RESULT FAIL: expected one hotrec RPM in /out/rpm, found ${#mains[@]}"; exit 1; }
[ "${#exts[@]}" -eq 1 ] || { echo "START-GATE RESULT FAIL: expected one hotrec-gnome-shell-extension RPM in /out/rpm, found ${#exts[@]}"; exit 1; }
nevra=$(basename "${mains[0]}" .rpm)
version=${nevra#hotrec-}
version=${version%%-*}
sha=$(sha256sum "${mains[0]}" | cut -d' ' -f1)
echo "gate: $nevra sha256 $sha"

# No weak dependencies: the program must start without the optional packages. The extension package
# is installed as well: it is what pulls in gnome-shell, mutter and gnome-settings-daemon, the
# desktop that `hotrec autostart` talks to. dbus-daemon and dconf are the two parts of a GNOME
# session that nothing of the program requires and the session probe needs (the buses, and the
# store of the keys the shortcuts are written to).
gate_dnf install --setopt=install_weak_deps=false "${mains[0]}" "${exts[0]}" dbus-daemon dconf
set +e

status=0
# the install is checked with rpm: an image with no rpm cannot pass, the step is not left out
if command -v rpm >/dev/null 2>&1; then
    for name in hotrec hotrec-gnome-shell-extension; do
        installed=$(rpm -q --qf '%{NVRA}' "$name")
        want=$(basename "$(ls /out/rpm/"$name"-[0-9]*.noarch.rpm)" .rpm)
        if [ "$installed" = "$want" ]; then
            echo "START-GATE rpm PASS rpm -q $name: $installed"
        else
            echo "START-GATE rpm FAIL rpm -q $name gives $installed, the file is $want"
            status=1
        fi
    done
else
    echo "START-GATE rpm FAIL there is no rpm in the image: the install cannot be checked"
    status=1
fi

cd "$(mktemp -d)" || exit 1
python3 -I /gate/probe_installed.py "$version" || status=1
python3 -I /gate/probe_session.py || status=1

if [ "$status" -eq 0 ]; then
    echo "START-GATE RESULT PASS $nevra sha256 $sha"
else
    echo "START-GATE RESULT FAIL $nevra sha256 $sha"
fi
exit "$status"
