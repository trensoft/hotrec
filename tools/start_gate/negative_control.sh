#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later
# The negative control of the start gate: on a tree that is broken on purpose in the start-up path of
# the dot, the gate must FAIL. A gate that cannot fail on a known bad tree is not a gate.
# usage: START_GATE_CHROOT=epel-10 tools/start_gate/negative_control.sh IMAGE TREE
#   IMAGE  the image of a leg, with START_GATE_CHROOT its COPR chroot (see start_gate.sh)
#   TREE   a git checkout; a copy of it is made and broken, TREE itself is not touched
# The break (the same one every time, so the result means the same): hotrec/indicator.py asks the
# AppIndicator library for a status that does not exist (`IndicatorStatus.ACTIVE` becomes
# `IndicatorStatus.ACTIVEX`): the module imports, the program runs up to the dot and dies there, the
# kind of break an import check does not see. The copy is committed (the source RPM is made from the
# commit), then start_gate.sh runs on it.
# Exit status 0 only when start_gate.sh ran both stages and the output of stage 2 shows the break and
# nothing else, each as a line of its own: every step before the dot passed ("START-GATE rpm PASS"
# twice, "version", "import", "cli", "catalog", "tools", "shell" and "loaded" PASS), the step
# "autostart" failed with the AttributeError that names ACTIVEX (the attribute the break made up), and
# the summary "START-GATE RESULT FAIL". A gate that passes is soft (exit 1). A gate that stopped
# before stage 2 ended, or failed for another reason (no network, a build error, a step before the
# dot that fails, an autostart that fails with another error), proves nothing and is not a pass
# either (exit 1).
set -uo pipefail

image=${1:?usage: START_GATE_CHROOT=epel-10 negative_control.sh IMAGE TREE}
tree=${2:?usage: START_GATE_CHROOT=epel-10 negative_control.sh IMAGE TREE}
here=$(cd "$(dirname "$0")" && pwd)
work=$(mktemp -d)
log=$work/gate.log
trap 'rm -rf "$work"' EXIT

git clone --quiet "$tree" "$work/tree" || { echo "NEGATIVE-CONTROL FAIL: cannot copy $tree"; exit 1; }
target=$work/tree/hotrec/indicator.py
if ! grep -q 'AppIndicator.IndicatorStatus.ACTIVE)' "$target"; then
    echo "NEGATIVE-CONTROL FAIL: the line to break is not in $target: the control must be updated"
    exit 1
fi
sed -i 's/AppIndicator.IndicatorStatus.ACTIVE)/AppIndicator.IndicatorStatus.ACTIVEX)/' "$target"
git -C "$work/tree" -c user.name=gate -c user.email=gate@localhost commit --quiet -am "negative control: broken on purpose" \
    || { echo "NEGATIVE-CONTROL FAIL: cannot commit the break"; exit 1; }

bash "$here/start_gate.sh" "$image" "$work/tree" 2>&1 | tee "$log"
rc=${PIPESTATUS[0]}

if [ "$rc" -eq 0 ]; then
    echo "NEGATIVE-CONTROL FAIL: the gate PASSED on the broken tree; it is soft, it does not catch a start-up error of the dot"
    exit 1
fi
# every line is anchored: a line of the build log that only contains the words does not count
missing=""
[ "$(grep -c '^START-GATE rpm PASS' "$log")" -eq 2 ] || missing="$missing rpm(x2)"
for step in version import cli catalog tools shell loaded; do
    grep -q "^START-GATE $step PASS" "$log" || missing="$missing $step"
done
grep -q '^START-GATE autostart FAIL .*AttributeError: .*ACTIVEX' "$log" || missing="$missing autostart(AttributeError ACTIVEX)"
grep -q '^START-GATE RESULT FAIL' "$log" || missing="$missing RESULT-FAIL"
if [ -z "$missing" ]; then
    echo "NEGATIVE-CONTROL PASS: the gate failed on the broken tree at the start of the dot, with the error of the break, as it must"
    exit 0
fi
echo "NEGATIVE-CONTROL FAIL: the gate failed (status $rc) but not as the broken tree does (every step before the dot passes," \
    "the autostart step fails with the AttributeError for ACTIVEX, in stage 2); missing:$missing: it proves nothing"
exit 1
