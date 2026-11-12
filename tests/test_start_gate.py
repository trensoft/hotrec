# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the scripts of the start gate (``tools/start_gate``) and the condition in the docs.

The gate itself needs podman or docker and the network (it builds the RPMs and installs them with
dnf in a container of each COPR chroot), so it is not run here. What is checked is what a change can
break without anybody seeing it: the scripts parse and stop on an error, the lines that make the
gate hard are there (each probe is a step that sets the failure status, the status is the exit
status, nothing is passed over with ``|| true``), and the condition of the release names the gate,
the chroots and the script that checks the condition. What the scripts do is run in
``test_start_gate_run.py`` and ``test_start_gate_verify.py``, with stand-ins for the commands. The
probes are in ``test_start_gate_probes.py``, the workflow in ``test_start_gate_workflow.py``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
GATE = REPO / "tools" / "start_gate"
RELEASING = REPO / "docs" / "RELEASING.md"
SHELL_SCRIPTS = (
    "start_gate.sh",
    "build.sh",
    "check.sh",
    "verify_checks.sh",
    "negative_control.sh",
)
PYTHON_SCRIPTS = (
    "probe_installed.py",
    "probe_session.py",
    "fake_login1.py",
    "fake_desktop.py",
)


def _lines(name: str) -> list:
    return (GATE / name).read_text(encoding="utf-8").splitlines()


def _code(name: str) -> list:
    """The lines of a script without the comments."""
    return [line for line in _lines(name) if not line.lstrip().startswith("#")]


@pytest.mark.parametrize("name", SHELL_SCRIPTS)
def test_shell_script_stops_on_the_first_error(name):
    """A failed command cannot be passed over: the shebang names bash and the strict mode is set.
    ``negative_control.sh`` has no ``-e``: it takes the exit status of the gate to judge it."""
    lines = _lines(name)
    assert lines[0] in ("#!/bin/bash", "#!/usr/bin/env bash")
    strict = "set -uo pipefail" if name == "negative_control.sh" else "set -euo pipefail"
    assert any(line.startswith(strict) for line in lines)


@pytest.mark.parametrize("name", SHELL_SCRIPTS + ("common.sh",))
def test_no_failure_is_passed_over_with_or_true(name):
    for line in _code(name):
        if name == "start_gate.sh" and "command -v docker" in line:
            continue  # the choice of the engine: no podman and no docker is an error of its own
        assert "|| true" not in line and "||true" not in line, line
        assert "|| :" not in line, line


@pytest.mark.parametrize("name", ["start_gate.sh", "build.sh", "verify_checks.sh"])
def test_the_strict_mode_is_never_turned_off(name):
    assert not [line for line in _code(name) if line.strip().startswith(("set +e", "set +o"))]


def test_check_turns_off_the_exit_on_error_once_and_only_after_the_install():
    """The probes must all run, so ``set -e`` goes off after the install; what ends a failed probe
    is ``|| status=1`` and the exit status at the end. The install (a failed one stops the script)
    comes first."""
    code = _code("check.sh")
    assert len([line for line in code if line.strip() == "set +e"]) == 1
    off = code.index("set +e")
    install = [i for i, line in enumerate(code) if "gate_dnf install" in line]
    assert install and install[0] < off


def test_check_installs_without_weak_dependencies():
    assert any(
        "gate_dnf install --setopt=install_weak_deps=false" in line for line in _code("check.sh")
    )


def test_check_installs_both_rpms_and_what_the_session_needs():
    line = [ln for ln in _code("check.sh") if "gate_dnf install" in ln][0]
    assert '"${mains[0]}" "${exts[0]}" dbus-daemon dconf' in line


def test_check_runs_both_probes_and_a_failure_of_either_is_the_status():
    code = [line.strip() for line in _code("check.sh")]
    assert 'python3 -I /gate/probe_installed.py "$version" || status=1' in code
    assert "python3 -I /gate/probe_session.py || status=1" in code
    assert code[-1] == 'exit "$status"'


def test_check_fails_without_rpm():
    text = "\n".join(_code("check.sh"))
    assert "START-GATE rpm FAIL there is no rpm" in text
    assert "START-GATE rpm FAIL rpm -q" in text


def test_check_takes_the_chroot_from_the_matrix_and_puts_it_in_the_repository():
    code = "\n".join(_code("check.sh"))
    assert "chroot=${START_GATE_CHROOT:?START_GATE_CHROOT is not set}" in code
    assert 'gate_copr_repo "$chroot"' in code


def test_the_copr_repository_holds_gpu_screen_recorder_only():
    """Hotrec itself must come from the file built in stage 1: the project has its own hotrec."""
    text = (GATE / "common.sh").read_text(encoding="utf-8")
    assert "includepkgs=gpu-screen-recorder" in text
    assert "gpgcheck=1" in text and "enabled=1" in text


def test_build_does_not_swallow_a_failure_of_rpmbuild():
    """rpmbuild ends with 11 when %generate_buildrequires names more build requirements: that code
    is the only one that is answered with another round, and the rounds are limited; any other
    non-zero code ends the stage."""
    text = "\n".join(_code("build.sh"))
    assert 'rpmbuild --rebuild --define "_topdir /out/build" "$srpm" || rc=$?' in text
    assert '[ "$rc" -eq 11 ] || break' in text
    assert 'if [ "$round" -ge "$max_rounds" ]; then' in text
    assert "max_rounds=5" in text
    assert '[ "$rc" -ne 0 ]' in text and 'exit "$rc"' in text


@pytest.mark.parametrize("name", PYTHON_SCRIPTS)
def test_python_script_parses(name):
    ast.parse((GATE / name).read_text(encoding="utf-8"), filename=name)


@pytest.mark.parametrize("name", SHELL_SCRIPTS + PYTHON_SCRIPTS)
def test_script_is_executable(name):
    assert (GATE / name).stat().st_mode & 0o111, f"{name} is not executable"


def test_the_condition_names_the_gate():
    text = RELEASING.read_text(encoding="utf-8")
    assert "No build of `hotrec` is started in the COPR project unless all of these hold" in text
    assert "The start gate is green on the commit that the build will take" in text
    assert "if one chroot did not run, there is no build" in text


def test_the_condition_makes_verify_checks_the_step_before_the_build():
    text = RELEASING.read_text(encoding="utf-8")
    assert "tools/start_gate/verify_checks.sh <sha>" in text
    assert "It is the required step before the build" in text
    assert "the chroot list of the COPR project is read from the" in text
    assert "COPR API, not from a file" in text
    assert "the commit is the **head of `master` now**" in text
    assert "tools/start_gate/negative_control.sh" in text


def test_the_docs_say_what_the_gate_does_not_measure():
    text = RELEASING.read_text(encoding="utf-8")
    assert "## What the gate does not measure" in text
    assert "A recording." in text
