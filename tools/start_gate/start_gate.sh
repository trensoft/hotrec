#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later
# The start gate of one chroot: build the RPMs from the tree, install them in a clean container, start
# the program there in a headless GNOME session.
# usage: START_GATE_CHROOT=epel-10 tools/start_gate/start_gate.sh IMAGE [TREE]
#   IMAGE  a container image: quay.io/centos/centos:stream10, registry.fedoraproject.org/fedora:43, ...
#   TREE   the git checkout to test; default the checkout this script is in
#   START_GATE_CHROOT  the COPR chroot of the image (epel-10, fedora-43, fedora-44, fedora-45,
#          fedora-rawhide), without the architecture; gpu-screen-recorder is taken from that chroot of
#          the COPR project
# Needs podman or docker (START_GATE_ENGINE=docker|podman picks one). Not started by the tests: it
# downloads packages (CI runs it, see .github/workflows/start-gate.yml, and docs/RELEASING.md says
# when). The scripts it runs in the containers come from this directory, so the same gate can test
# another tree: TREE may be a checkout that does not have this directory.
set -euo pipefail

image=${1:?usage: START_GATE_CHROOT=epel-10 start_gate.sh IMAGE [TREE]}
here=$(cd "$(dirname "$0")" && pwd)
tree=$(cd "${2:-$here/../..}" && pwd)
engine=${START_GATE_ENGINE:-$(command -v podman || command -v docker || true)}
[ -n "$engine" ] || { echo "start_gate.sh: no podman or docker" >&2; exit 2; }
[ -e "$tree/.copr/Makefile" ] || { echo "start_gate.sh: $tree has no .copr/Makefile" >&2; exit 2; }
[[ ${START_GATE_CHROOT:-} =~ ^(epel-[0-9]+|fedora-([0-9]+|rawhide))$ ]] \
    || { echo "start_gate.sh: START_GATE_CHROOT is '${START_GATE_CHROOT:-}', not a COPR chroot name like epel-10" >&2; exit 2; }

out=$(mktemp -d)
trap 'rm -rf "$out"' EXIT
chmod 777 "$out"

echo "== stage 1: build the RPMs from $tree in $image ($START_GATE_CHROOT)"
"$engine" run --rm -v "$tree":/src:ro -v "$here":/gate:ro -v "$out":/out "$image" bash /gate/build.sh
echo "== stage 2: install and start it in a clean $image ($START_GATE_CHROOT)"
"$engine" run --rm -e START_GATE_CHROOT -v "$here":/gate:ro -v "$out":/out:ro "$image" bash /gate/check.sh
