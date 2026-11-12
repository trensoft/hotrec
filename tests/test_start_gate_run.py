# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

"""The scripts of the start gate (``tools/start_gate``), run with stand-ins for dnf, rpm, rpmbuild
and the container engine (``tests/start_gate_helpers.py``).

The gate itself needs a container engine and the network, so CI runs it
(``.github/workflows/start-gate.yml``). What is checked here is its logic, the part that makes it a
gate: a failed step ends the script with a non-zero status, no step is left out, the install has no
weak dependencies, a failure of ``rpmbuild`` is not passed over, and the packages that are tested
are the ones that stage 1 made. A change that makes the gate soft fails one of these tests.
"""

from __future__ import annotations

import subprocess

import pytest
from start_gate_helpers import (
    CHROOT,
    EXT_NEVRA,
    GATE,
    NEVRA,
    Box,
    fake_engine,
    make_tree,
    point_paths,
    stub,
)


@pytest.fixture
def box(tmp_path):
    return Box(tmp_path)


# ---- check.sh: stage 2 ----------------------------------------------------------------------


@pytest.fixture
def check(box):
    """check.sh in a box: the two RPMs in /out/rpm, rpm -q that agrees with them, two probes that
    pass."""
    rpm_dir = box.out / "rpm"
    rpm_dir.mkdir()
    (rpm_dir / f"{NEVRA}.rpm").write_bytes(b"not a real rpm")
    (rpm_dir / f"{EXT_NEVRA}.rpm").write_bytes(b"not a real rpm either")
    stub(
        box.bin / "rpm",
        'case "$4" in\n'
        f'    hotrec) echo -n "${{STUB_RPM_MAIN:-{NEVRA}}}" ;;\n'
        f'    hotrec-gnome-shell-extension) echo -n "${{STUB_RPM_EXT:-{EXT_NEVRA}}}" ;;\n'
        "    *) exit 1 ;;\n"
        "esac\n",
    )
    stub(
        box.bin / "python3",
        'echo "python3 $*" >> "$STUB_LOG"\n'
        'case "$*" in\n'
        '    *probe_installed*) exit "${STUB_INSTALLED_RC:-0}" ;;\n'
        '    *probe_session*) exit "${STUB_SESSION_RC:-0}" ;;\n'
        "esac\n"
        "exit 99\n",
    )
    script = box.script("check.sh")
    return lambda **env: box.run(script, **{"START_GATE_CHROOT": CHROOT, **env})


def _last_line(result) -> str:
    return result.stdout.strip().splitlines()[-1]


def test_check_passes_when_everything_passes(box, check):
    result = check()
    assert result.returncode == 0, result.stdout + result.stderr
    assert _last_line(result).startswith(f"START-GATE RESULT PASS {NEVRA} sha256 ")
    assert f"START-GATE rpm PASS rpm -q hotrec: {NEVRA}" in result.stdout
    assert f"START-GATE rpm PASS rpm -q hotrec-gnome-shell-extension: {EXT_NEVRA}" in result.stdout


def test_check_puts_the_copr_repository_of_the_chroot_before_the_install(box, check):
    check()
    calls = box.calls()
    assert calls[:2] == ["gate_repos", f"gate_copr_repo {CHROOT}"]
    assert calls[3].startswith("dnf install")


def test_check_takes_the_language_filter_of_the_image_off_right_before_the_install(box, check):
    # the images keep one language: without this the .mo files of the package are not installed
    check()
    calls = box.calls()
    assert calls[2] == "gate_all_languages"
    assert calls[3].startswith("dnf install")
    assert calls.count("gate_all_languages") == 1


def test_check_needs_the_chroot(box, check):
    result = check(START_GATE_CHROOT="")
    assert result.returncode != 0
    assert "START_GATE_CHROOT is not set" in result.stderr
    assert not [call for call in box.calls() if call.startswith(("dnf", "python3"))]


def test_check_installs_both_rpms_without_weak_dependencies(box, check):
    check()
    installs = [call for call in box.calls() if call.startswith("dnf install")]
    assert len(installs) == 1
    assert "--setopt=install_weak_deps=false" in installs[0]
    assert str(box.out / "rpm" / f"{NEVRA}.rpm") in installs[0]
    assert str(box.out / "rpm" / f"{EXT_NEVRA}.rpm") in installs[0]
    assert installs[0].endswith(" dbus-daemon dconf")


def test_check_runs_both_probes_from_the_installed_copy(box, check):
    check()
    probes = [call for call in box.calls() if call.startswith("python3")]
    # -I: no current directory and no PYTHONPATH, so the installed copy is the one that is tested
    assert probes == [
        f"python3 -I {box.gate}/probe_installed.py 1.2.3",
        f"python3 -I {box.gate}/probe_session.py",
    ]


@pytest.mark.parametrize("failing", ["STUB_INSTALLED_RC", "STUB_SESSION_RC"])
def test_check_fails_when_a_probe_fails_and_still_runs_the_other(box, check, failing):
    result = check(**{failing: "1"})
    assert result.returncode == 1
    assert _last_line(result).startswith(f"START-GATE RESULT FAIL {NEVRA}")
    assert len([c for c in box.calls() if c.startswith("python3")]) == 2


def test_check_stops_when_the_install_fails(box, check):
    result = check(STUB_DNF_RC="1")
    assert result.returncode != 0
    assert not [call for call in box.calls() if call.startswith("python3")]
    assert "START-GATE RESULT PASS" not in result.stdout


@pytest.mark.parametrize(
    "variable, name",
    [("STUB_RPM_MAIN", "hotrec"), ("STUB_RPM_EXT", "hotrec-gnome-shell-extension")],
)
def test_check_fails_when_rpm_q_names_another_package(box, check, variable, name):
    result = check(**{variable: f"{name}-0.1.6-1.fc43.noarch"})
    assert result.returncode == 1
    assert f"START-GATE rpm FAIL rpm -q {name} gives {name}-0.1.6-1.fc43.noarch" in result.stdout
    assert _last_line(result).startswith("START-GATE RESULT FAIL")
    assert len([c for c in box.calls() if c.startswith("python3")]) == 2


def test_check_fails_when_the_image_has_no_rpm(box, check):
    (box.bin / "rpm").unlink()
    result = check()
    assert result.returncode == 1
    assert "START-GATE rpm FAIL there is no rpm" in result.stdout
    assert _last_line(result).startswith("START-GATE RESULT FAIL")


@pytest.mark.parametrize("count", [0, 2])
def test_check_wants_exactly_one_hotrec_rpm(box, check, count):
    rpm_dir = box.out / "rpm"
    (rpm_dir / f"{NEVRA}.rpm").unlink()
    for number in range(count):
        (rpm_dir / f"hotrec-1.2.{number}-1.fc43.noarch.rpm").write_bytes(b"x")
    result = check()
    assert result.returncode == 1
    assert "START-GATE RESULT FAIL: expected one hotrec RPM" in result.stdout
    assert not [call for call in box.calls() if call.startswith("python3")]


@pytest.mark.parametrize("count", [0, 2])
def test_check_wants_exactly_one_extension_rpm(box, check, count):
    rpm_dir = box.out / "rpm"
    (rpm_dir / f"{EXT_NEVRA}.rpm").unlink()
    for number in range(count):
        (rpm_dir / f"hotrec-gnome-shell-extension-1.2.{number}-1.fc43.noarch.rpm").write_bytes(b"x")
    result = check()
    assert result.returncode == 1
    assert "START-GATE RESULT FAIL: expected one hotrec-gnome-shell-extension RPM" in result.stdout
    assert not [call for call in box.calls() if call.startswith("python3")]


def test_check_does_not_take_the_extension_rpm_for_the_program(box, check):
    """``hotrec-gnome-shell-extension-1.2.3`` starts with ``hotrec-``: only a name that continues
    with a digit is the program (the version is read from it)."""
    (box.out / "rpm" / f"{NEVRA}.rpm").unlink()
    result = check()
    assert result.returncode == 1
    assert "expected one hotrec RPM in" in result.stdout and ", found 0" in result.stdout


# ---- build.sh: stage 1 ----------------------------------------------------------------------


@pytest.fixture
def build(box):
    """build.sh in a box: make makes a source RPM, rpmbuild answers with the codes in
    STUB_RPMBUILD_RCS (one per call, 0 after the list), and an RPM of an earlier run is in the
    build directory, as it can be left there."""
    stub(
        box.bin / "make",
        'echo "make $*" >> "$STUB_LOG"\n'
        'for arg; do case "$arg" in outdir=*) outdir=${arg#outdir=} ;; esac; done\n'
        'mkdir -p "$outdir"; : > "$outdir/hotrec-1.2.3-1.src.rpm"\n',
    )
    stub(
        box.bin / "rpmbuild",
        'echo "rpmbuild $*" >> "$STUB_LOG"\n'
        'n=0; [ -f "$STUB_LOG.count" ] && read -r n < "$STUB_LOG.count"\n'
        'n=$((n + 1)); echo "$n" > "$STUB_LOG.count"\n'
        'read -r -a rcs <<< "${STUB_RPMBUILD_RCS:-0}"\n'
        "rc=${rcs[$((n - 1))]:-0}\n"
        'if [ "$rc" -eq 0 ]; then\n'
        '    mkdir -p "$STUB_OUT/build/RPMS/noarch"\n'
        f'    : > "$STUB_OUT/build/RPMS/noarch/{NEVRA}.rpm"\n'
        f'    : > "$STUB_OUT/build/RPMS/noarch/{EXT_NEVRA}.rpm"\n'
        "fi\n"
        'exit "$rc"\n',
    )
    (box.src / ".copr").mkdir()
    script = box.script("build.sh")
    return lambda **env: box.run(script, STUB_OUT=str(box.out), **env)


def test_build_makes_both_rpms_and_copies_them_out(box, build):
    result = build()
    assert result.returncode == 0, result.stdout + result.stderr
    assert sorted(p.name for p in (box.out / "rpm").iterdir()) == sorted(
        [f"{NEVRA}.rpm", f"{EXT_NEVRA}.rpm"]
    )
    calls = box.calls()
    assert any(call.startswith("make -f") and " srpm outdir=" in call for call in calls)
    assert any(call.startswith("dnf builddep") and call.endswith(".src.rpm") for call in calls)


def test_build_installs_the_second_round_of_build_requirements_on_code_11(box, build):
    result = build(STUB_RPMBUILD_RCS="11 0")
    assert result.returncode == 0, result.stdout + result.stderr
    calls = box.calls()
    assert len([c for c in calls if c.startswith("rpmbuild")]) == 2
    assert any("buildreqs.nosrc.rpm" in c and c.startswith("dnf builddep") for c in calls)


@pytest.mark.parametrize("codes, rounds", [("11 11 0", 3), ("11 11 11 0", 4), ("11 11 11 11 0", 5)])
def test_build_goes_on_while_rpmbuild_asks_for_build_requirements(box, build, codes, rounds):
    """EL10 asks twice (pyproject-rpm-macros, then setuptools): one round more is not enough."""
    result = build(STUB_RPMBUILD_RCS=codes)
    assert result.returncode == 0, result.stdout + result.stderr
    calls = box.calls()
    assert len([c for c in calls if c.startswith("rpmbuild")]) == rounds
    # builddep of the build requirements once after every code 11
    nosrc = [c for c in calls if c.startswith("dnf builddep") and "buildreqs.nosrc.rpm" in c]
    assert len(nosrc) == rounds - 1
    assert sorted(p.name for p in (box.out / "rpm").iterdir()) == sorted(
        [f"{NEVRA}.rpm", f"{EXT_NEVRA}.rpm"]
    )


def test_build_fails_loudly_when_rpmbuild_still_asks_after_the_last_round(box, build):
    # the build never ends: the limit is the end, with the code 11 and a message, and no RPM
    stale = box.out / "build" / "RPMS" / "noarch"
    stale.mkdir(parents=True)
    (stale / f"{NEVRA}.rpm").write_bytes(b"left over")
    result = build(STUB_RPMBUILD_RCS="11 " * 20)
    assert result.returncode == 11
    assert "still asks for build requirements after 5 rounds" in result.stderr
    calls = box.calls()
    assert len([c for c in calls if c.startswith("rpmbuild")]) == 5
    assert len([c for c in calls if c.startswith("dnf builddep") and "buildreqs" in c]) == 4
    assert not list((box.out / "rpm").iterdir())


@pytest.mark.parametrize("codes, expected", [("1", 1), ("2", 2), ("11 1", 1), ("11 11 1", 1)])
def test_build_ends_with_the_failure_of_rpmbuild_and_copies_nothing(box, build, codes, expected):
    # RPMs left in the build directory (an earlier run) must not be taken for the result
    stale = box.out / "build" / "RPMS" / "noarch"
    stale.mkdir(parents=True)
    (stale / f"{NEVRA}.rpm").write_bytes(b"left over")
    result = build(STUB_RPMBUILD_RCS=codes)
    assert result.returncode == expected, result.stdout + result.stderr
    assert not list((box.out / "rpm").iterdir())


def test_build_stops_when_dnf_fails(box, build):
    result = build(STUB_DNF_RC="1")
    assert result.returncode != 0
    assert not [call for call in box.calls() if call.startswith("rpmbuild")]


def test_build_leaves_the_files_removable_for_whoever_started_the_container(box, build):
    # build.sh ends with chmod -R a+rwX on /out, also after a failure
    stub(box.bin / "chmod", 'echo "chmod $*" >> "$STUB_LOG"\n')
    build(STUB_RPMBUILD_RCS="1")
    assert any(call.startswith("chmod -R a+rwX") for call in box.calls())


# ---- start_gate.sh: the two containers -------------------------------------------------------


@pytest.fixture
def gate_run(box):
    tree = make_tree(box.root / "tree")

    def run(stage_rc=None, stage_output=None, **env):
        engine = fake_engine(box.root / "engine", stage_output or {}, stage_rc or {})
        return box.run(
            GATE / "start_gate.sh",
            "registry.example/image:1",
            str(tree),
            **{
                "START_GATE_ENGINE": str(engine),
                "START_GATE_CHROOT": CHROOT,
                "PATH": f"{box.bin}:/usr/bin",
                **env,
            },
        )

    return run


def test_start_gate_runs_the_two_stages_in_two_containers(box, gate_run):
    result = gate_run()
    assert result.returncode == 0, result.stdout + result.stderr
    stage1, stage2 = box.calls()
    assert stage1.endswith("bash /gate/build.sh") and stage2.endswith("bash /gate/check.sh")
    # stage 1 has the tree, stage 2 has not: the installed copy is what is tested
    assert f"{box.root / 'tree'}:/src:ro" in stage1 and ":/src" not in stage2
    assert ":/out registry.example/image:1 bash" in stage1
    assert ":/out:ro registry.example/image:1 bash" in stage2


def test_start_gate_passes_the_chroot_to_stage_2_only(box, gate_run):
    gate_run()
    stage1, stage2 = box.calls()
    assert "-e START_GATE_CHROOT" in stage2 and "START_GATE_CHROOT" not in stage1


def test_start_gate_does_not_start_stage_2_after_a_failed_stage_1(box, gate_run):
    result = gate_run(stage_rc={"build.sh": 7})
    assert result.returncode == 7
    assert len(box.calls()) == 1


def test_start_gate_ends_with_the_failure_of_stage_2(box, gate_run):
    result = gate_run(stage_rc={"check.sh": 1})
    assert result.returncode == 1
    assert len(box.calls()) == 2


def test_start_gate_without_an_engine_is_an_error(box):
    tree = make_tree(box.root / "tree")
    result = box.run(GATE / "start_gate.sh", "image", str(tree), START_GATE_CHROOT=CHROOT)
    assert result.returncode == 2
    assert "no podman or docker" in result.stderr


def test_start_gate_wants_a_tree_with_the_copr_makefile(box):
    result = box.run(
        GATE / "start_gate.sh",
        "image",
        str(box.root),
        START_GATE_ENGINE="/bin/true",
        START_GATE_CHROOT=CHROOT,
    )
    assert result.returncode == 2


@pytest.mark.parametrize(
    "chroot",
    ["", "fedora", "fedora-4x", "centos-10", "epel-", "fedora-43-x86_64", "fedora-rawhide;x"],
)
def test_start_gate_wants_a_copr_chroot_name(box, gate_run, chroot):
    result = gate_run(START_GATE_CHROOT=chroot)
    assert result.returncode == 2
    assert "not a COPR chroot name" in result.stderr
    assert not box.calls()


@pytest.mark.parametrize(
    "chroot", ["epel-10", "fedora-43", "fedora-44", "fedora-45", "fedora-rawhide"]
)
def test_start_gate_takes_the_names_of_the_copr_chroots(box, gate_run, chroot):
    assert gate_run(START_GATE_CHROOT=chroot).returncode == 0


# ---- negative_control.sh ---------------------------------------------------------------------

# stage 2 of the gate on the broken tree: every step before the dot passes, the autostart fails with
# the error of the break (the traceback is in the line, with the newlines as \n), the steps after it
# are not run
RPM_1 = "START-GATE rpm PASS rpm -q hotrec: hotrec-0.1.7-1.el10.noarch"
RPM_2 = "START-GATE rpm PASS rpm -q hotrec-gnome-shell-extension: x-0.1.7-1.el10.noarch"
BEFORE = (
    "START-GATE version PASS version 0.1.7",
    "START-GATE import PASS 13 modules import",
    "START-GATE cli PASS /usr/bin/hotrec: --version says hotrec 0.1.7",
    "START-GATE catalog PASS 1 catalog",
    "START-GATE tools PASS gpu-screen-recorder linked",
    "START-GATE shell PASS GNOME Shell 49.10 is up",
    "START-GATE loaded PASS GNOME Shell 49.10 knows hotrec-dot@trensoft.github.io, state 6",
)
AUTOSTART_FAIL = (
    "START-GATE autostart FAIL Failed: hotrec autostart ended with status 1 at its start: "
    "'...main\\n    return _do_autostart(recorder)\\nAttributeError: type object "
    "\\'IndicatorStatus\\' has no attribute \\'ACTIVEX\\'. Did you mean: \\'ACTIVE\\'?\\n'"
)
AFTER = (
    "START-GATE extension FAIL not run: the step autostart failed",
    "START-GATE dot FAIL not run: the step autostart failed",
)
RESULT_FAIL = "START-GATE RESULT FAIL x sha256 y"


def stage2(*lines):
    return {"check.sh": "\n".join(lines)}


FAIL_AUTOSTART = stage2(RPM_1, RPM_2, *BEFORE, AUTOSTART_FAIL, *AFTER, RESULT_FAIL)


@pytest.fixture
def control(box):
    tree = _git_tree(box.root / "tree")

    def run(stage_rc=None, stage_output=None, tree_path=tree):
        engine = fake_engine(box.root / "engine", stage_output or {}, stage_rc or {})
        return box.run(
            GATE / "negative_control.sh",
            "registry.example/image:1",
            str(tree_path),
            START_GATE_ENGINE=str(engine),
            START_GATE_CHROOT=CHROOT,
            PATH=f"{box.bin}:/usr/bin",
            HOME=str(box.root),
        )

    return run


def _git_tree(path):
    """A git checkout with a ``.copr/Makefile`` and the line of ``hotrec/indicator.py`` that the
    control breaks."""
    make_tree(path)
    (path / "hotrec").mkdir()
    (path / "hotrec" / "indicator.py").write_text(
        "    indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)\n"
        "    indicator.set_status(AppIndicator.IndicatorStatus.PASSIVE)\n",
        encoding="utf-8",
    )
    git = ["git", "-C", str(path), "-c", "user.name=t", "-c", "user.email=t@localhost"]
    subprocess.run(git + ["init", "--quiet"], check=True)
    subprocess.run(git + ["add", "."], check=True)
    subprocess.run(git + ["commit", "--quiet", "-m", "tree"], check=True)
    return path


def test_the_control_passes_when_the_gate_fails_at_the_autostart(control):
    result = control({"check.sh": 1}, FAIL_AUTOSTART)
    assert result.returncode == 0, result.stdout
    assert "NEGATIVE-CONTROL PASS" in result.stdout


def test_the_control_breaks_a_copy_of_the_tree_and_leaves_the_tree_alone(box, control):
    tree = box.root / "tree"
    control({"check.sh": 1}, FAIL_AUTOSTART)
    stage1 = box.calls()[0]
    copy = [part for part in stage1.split() if part.endswith(":/src:ro")][0].split(":")[0]
    assert copy != str(tree)
    seen = (box.root / "calls.log.src").read_text(encoding="utf-8")
    assert "IndicatorStatus.ACTIVEX)" in seen and "IndicatorStatus.PASSIVE)" in seen
    assert "IndicatorStatus.ACTIVE)" not in seen
    assert "ACTIVEX" not in (tree / "hotrec" / "indicator.py").read_text(encoding="utf-8")


def test_the_control_fails_when_the_gate_passes_on_the_bad_tree(control):
    result = control({}, stage2("START-GATE RESULT PASS x sha256 y"))
    assert result.returncode == 1
    assert "it is soft" in result.stdout


@pytest.mark.parametrize(
    "rc, output",
    [
        ({"build.sh": 1}, {}),  # the build broke: nothing was started
        ({"check.sh": 1}, stage2(RPM_1, RPM_2, *BEFORE, RESULT_FAIL)),  # not the autostart
        ({"check.sh": 1}, stage2("START-GATE shell FAIL x", RESULT_FAIL)),
        ({"check.sh": 1}, stage2(RPM_1, RPM_2, *BEFORE, AUTOSTART_FAIL)),  # no summary: did not end
        ({"check.sh": 1}, stage2("network is unreachable")),
    ],
)
def test_the_control_proves_nothing_when_the_gate_fails_for_another_reason(control, rc, output):
    result = control(rc, output)
    assert result.returncode == 1
    assert "NEGATIVE-CONTROL FAIL" in result.stdout


@pytest.mark.parametrize(
    "autostart",
    [
        # the autostart fails, but not because of the break
        "START-GATE autostart FAIL Failed: hotrec autostart ended with status 1 at its start: 'x'",
        "START-GATE autostart FAIL Failed: no notification 'Keyboard shortcuts are set'",
        "START-GATE autostart FAIL Failed: the dot is not registered after 60 s",
        "START-GATE autostart FAIL TimeoutExpired: hotrec shortcuts status ACTIVEX",  # word only
        "START-GATE autostart FAIL AttributeError: 'NoneType' object has no attribute 'get'",
        "START-GATE autostart FAIL",  # no reason at all
    ],
)
def test_the_control_is_red_when_the_autostart_fails_for_another_reason_than_the_break(
    control, autostart
):
    """The gate fails on the same step but not for the reason of the break: not the proof."""
    result = control({"check.sh": 1}, stage2(RPM_1, RPM_2, *BEFORE, autostart, *AFTER, RESULT_FAIL))
    assert result.returncode == 1, result.stdout
    assert "NEGATIVE-CONTROL FAIL" in result.stdout
    assert "NEGATIVE-CONTROL PASS" not in result.stdout


@pytest.mark.parametrize(
    "which", range(len(BEFORE) + 2), ids=["rpm1", "rpm2", *[line.split()[1] for line in BEFORE]]
)
def test_the_control_is_red_when_a_step_before_the_dot_does_not_pass(control, which):
    """A step before the dot failed or did not run: the install or the toolkit is broken, and the
    failure of the autostart proves nothing about the break. Each of the nine lines, in turn, is
    replaced by a FAIL of the same step, and left out."""
    lines = [RPM_1, RPM_2, *BEFORE]
    tail = (AUTOSTART_FAIL, *AFTER, RESULT_FAIL)
    step = lines[which].split()[1]
    failed = lines[:which] + [f"START-GATE {step} FAIL x"] + lines[which + 1 :]
    absent = lines[:which] + lines[which + 1 :]
    for before in (failed, absent):
        result = control({"check.sh": 1}, stage2(*before, *tail))
        assert result.returncode == 1, (which, before, result.stdout)
        assert "NEGATIVE-CONTROL FAIL" in result.stdout


@pytest.mark.parametrize("which", range(len(BEFORE) + 4), ids=lambda i: str(i))
@pytest.mark.parametrize("prefix", ["x ", "  ", "+ "], ids=["word", "indent", "diff"])
def test_the_control_wants_every_line_of_stage_2_as_a_line_of_its_own(control, which, prefix):
    """A line that only contains the words (a log of the build, an echo of a command) counts for
    nothing: each line the control looks for is matched at the start of the line."""
    lines = [RPM_1, RPM_2, *BEFORE, AUTOSTART_FAIL, RESULT_FAIL]
    lines[which] = prefix + lines[which]
    result = control({"check.sh": 1}, stage2(*lines))
    assert result.returncode == 1, result.stdout


def test_the_control_fails_when_the_line_to_break_is_not_there(box, control):
    tree = box.root / "tree"
    (tree / "hotrec" / "indicator.py").write_text("nothing\n", encoding="utf-8")
    git = ["git", "-C", str(tree), "-c", "user.name=t", "-c", "user.email=t@localhost"]
    subprocess.run(git + ["commit", "--quiet", "-am", "moved"], check=True)
    result = control({"check.sh": 1}, FAIL_AUTOSTART)
    assert result.returncode == 1
    assert "the line to break is not in" in result.stdout
    assert not box.calls()


# ---- common.sh: the repositories of the image ------------------------------------------------


@pytest.fixture
def common(box):
    """The real ``common.sh``, with the paths of the image (``/etc/os-release``,
    ``/etc/yum.repos.d``) pointed into the box and a ``dnf`` that logs: a function of the file is
    called in bash, and what it did is read from the log and the repository file."""
    repos = box.root / "yum.repos.d"
    repos.mkdir()
    stub(box.bin / "dnf", 'echo "dnf $*" >> "$STUB_LOG"\n')
    release = box.root / "os-release"

    rpm_etc = box.root / "etc-rpm"
    rpm_etc.mkdir()

    def call(function, os_release="", *args):
        release.write_text(os_release, encoding="utf-8")
        text = point_paths(
            (GATE / "common.sh").read_text(encoding="utf-8"),
            {"/etc/os-release": release, "/etc/yum.repos.d": repos, "/etc/rpm": rpm_etc},
        )
        (box.gate / "common_real.sh").write_text(text, encoding="utf-8")
        return box.run_function(box.gate / "common_real.sh", function, *args)

    call.repos = repos
    call.rpm_etc = rpm_etc
    return call


CENTOS = 'ID="centos"\nID_LIKE="rhel fedora"\nPRETTY_NAME="CentOS Stream 10"\n'
FEDORA = 'ID=fedora\nPRETTY_NAME="Fedora Linux 43"\n'


def test_repos_of_el10_are_crb_and_epel(box, common):
    result = common("gate_repos", CENTOS)
    assert result.returncode == 0, result.stderr
    assert box.calls() == [
        "dnf -y install dnf-plugins-core",
        "dnf -y config-manager --set-enabled crb",
        "dnf -y install epel-release",
    ]
    assert "image is CentOS Stream 10" in result.stdout


def test_repos_of_fedora_are_the_ones_it_has(box, common):
    result = common("gate_repos", FEDORA)
    assert result.returncode == 0, result.stderr
    assert box.calls() == []
    assert "image is Fedora Linux 43" in result.stdout


@pytest.mark.parametrize("chroot", ["epel-10", "fedora-43", "fedora-45", "fedora-rawhide"])
def test_the_copr_repository_is_the_chroot_it_is_given_for_one_package(box, common, chroot):
    result = common("gate_copr_repo", FEDORA, chroot)
    assert result.returncode == 0, result.stderr
    text = (common.repos / "gate-copr-gpu-screen-recorder.repo").read_text(encoding="utf-8")
    base = "https://download.copr.fedorainfracloud.org/results/trensoft/hotrec"
    assert f"baseurl={base}/{chroot}-x86_64/\n" in text
    assert "includepkgs=gpu-screen-recorder\n" in text
    assert "gpgcheck=1\n" in text and f"gpgkey={base}/pubkey.gpg\n" in text
    assert "enabled=1\n" in text and text.startswith("[gate-copr-gpu-screen-recorder]\n")
    assert text.count("[") == 1


def test_the_copr_repository_needs_the_chroot(box, common):
    result = common("gate_copr_repo", FEDORA)
    assert result.returncode != 0
    assert not list(common.repos.iterdir())


def test_dnf_is_run_without_questions(box, common):
    common("gate_dnf", FEDORA, "install", "x")
    assert box.calls() == ["dnf -y install x"]


LANG_FILTER = "macros.image-language-conf"


@pytest.mark.parametrize("value", ["%_install_langs en_US\n", "%_install_langs C.UTF-8\n"])
def test_the_language_filter_of_the_image_is_removed_and_nothing_else(box, common, value):
    # Fedora images say en_US, CentOS Stream says C.UTF-8: either leaves out the .mo files
    (common.rpm_etc / LANG_FILTER).write_text(value, encoding="utf-8")
    (common.rpm_etc / "macros.dist").write_text("%dist .fc43\n", encoding="utf-8")
    result = common("gate_all_languages", FEDORA)
    assert result.returncode == 0, result.stderr
    assert sorted(path.name for path in common.rpm_etc.iterdir()) == ["macros.dist"]
    assert "filter of the image" in result.stdout and "is off" in result.stdout


def test_an_image_without_the_language_filter_is_not_an_error(box, common):
    result = common("gate_all_languages", FEDORA)
    assert result.returncode == 0, result.stderr
    assert list(common.rpm_etc.iterdir()) == []
