# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the workflows of the start gate (``.github/workflows/start-gate.yml`` and
``negative-control.yml``).

The legs of the matrix of the first must be the chroot list that ``docs/RELEASING.md`` names as the
chroots of the COPR project, and it must run on the events a COPR build of master depends on. The
lines that make it a hard gate are checked too: no ``continue-on-error``, no leg that stops the
others, a time limit on every job, no token kept in ``.git/config``. The second is the negative
control (a broken tree must make the gate fail): a file of its own, run by hand, that leaves no
check named like a leg of the gate on a commit.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
WORKFLOW = REPO / ".github" / "workflows" / "start-gate.yml"
NEGATIVE = REPO / ".github" / "workflows" / "negative-control.yml"
RELEASING = REPO / "docs" / "RELEASING.md"


def _text(path: Path = WORKFLOW) -> str:
    return path.read_text(encoding="utf-8")


def _matrix_chroots() -> list:
    return re.findall(r"^\s+- chroot: (\S+)\s*$", _text(), re.M)


def _documented_chroots() -> list:
    for line in RELEASING.read_text(encoding="utf-8").splitlines():
        if line.startswith("Start gate chroots"):
            return re.findall(r"`((?:epel|fedora)-[a-z0-9]+)`", line)
    raise AssertionError("docs/RELEASING.md has no line that starts with 'Start gate chroots'")


def test_matrix_is_the_documented_copr_chroot_list():
    matrix = _matrix_chroots()
    assert matrix, "no leg in the matrix of the workflow"
    assert len(set(matrix)) == len(matrix), f"a chroot twice in the matrix: {matrix}"
    assert sorted(matrix) == sorted(_documented_chroots())


def test_epel_10_leg_comes_first():
    assert _matrix_chroots()[0] == "epel-10"


def test_every_leg_has_an_image_that_fits_its_chroot():
    pairs = re.findall(r"- chroot: (\S+)\n\s+image: (\S+)", _text())
    assert [chroot for chroot, _ in pairs] == _matrix_chroots()
    for chroot, image in pairs:
        assert ":" in image and "latest" not in image, f"{chroot}: the image has no tag: {image}"
        if chroot == "epel-10":
            assert image == "quay.io/centos/centos:stream10"
        else:
            assert image == f"registry.fedoraproject.org/fedora:{chroot.split('-', 1)[1]}", chroot


def test_workflow_runs_on_pull_requests_and_on_pushes_to_master():
    text = _text()
    assert re.search(r"^on:\n(?:.*\n)*?  pull_request:", text, re.M)
    assert re.search(r"^    branches: \[master\]", text, re.M)


def test_no_leg_stops_the_others():
    assert re.search(r"^      fail-fast: false$", _text(), re.M)


def _jobs(path: Path = WORKFLOW) -> dict:
    """The text of every job of a workflow, by the name of the job."""
    _head, _, rest = _text(path).partition("\njobs:\n")
    assert rest, "the workflow has no jobs"
    parts = re.split(r"^  ([a-z][a-z-]*):\n", rest, flags=re.M)
    return dict(zip(parts[1::2], parts[2::2]))


def test_the_gate_workflow_has_the_gate_job_and_nothing_else():
    assert sorted(_jobs()) == ["start-gate"]
    assert sorted(_jobs(NEGATIVE)) == ["negative-control"]


def test_the_gate_workflow_has_no_run_by_hand_and_no_condition_on_a_job():
    """A leg that is skipped leaves a check named ``start gate (${{ matrix.chroot }})`` on the
    commit, which ``verify_checks.sh`` takes for a leg with no chroot and fails on. So the gate
    has no job-level ``if``, and the run by hand lives in the other file."""
    text = _text()
    assert not re.search(r"^\s+if:", text, re.M)
    assert "workflow_dispatch" not in text
    assert "github.event_name" not in text


def test_no_job_may_fail_without_failing_the_check():
    assert "continue-on-error" not in _text()
    assert "continue-on-error" not in _text(NEGATIVE)


@pytest.mark.parametrize(
    "path", [WORKFLOW, NEGATIVE], ids=["start-gate.yml", "negative-control.yml"]
)
def test_every_job_has_a_time_limit_that_is_a_limit(path):
    for name, job in _jobs(path).items():
        limits = re.findall(r"^    timeout-minutes: (\d+)$", job, re.M)
        assert len(limits) == 1, f"{name}: no timeout-minutes"
        assert 1 <= int(limits[0]) <= 60, f"{name}: timeout-minutes {limits[0]}"


@pytest.mark.parametrize(
    "path", [WORKFLOW, NEGATIVE], ids=["start-gate.yml", "negative-control.yml"]
)
def test_the_workflow_token_only_reads_in_every_workflow(path):
    assert re.search(r"^permissions:\n  contents: read$", _text(path), re.M)


@pytest.mark.parametrize(
    "path", [WORKFLOW, NEGATIVE], ids=["start-gate.yml", "negative-control.yml"]
)
def test_the_token_is_not_kept_in_the_checkout(path):
    """The code under test runs in containers that read the checkout: the token of the job is not
    left in ``.git/config`` (``persist-credentials: false`` on every checkout)."""
    text = _text(path)
    checkouts = re.findall(
        r"uses: actions/checkout@v4\n((?:        with:\n(?:          .*\n)*)?)", text
    )
    assert len(checkouts) == text.count("actions/checkout")
    assert len(checkouts) == 1
    for options in checkouts:
        assert "persist-credentials: false" in options


def test_the_gate_job_runs_the_gate_script_on_the_image_and_chroot_of_its_leg():
    job = _jobs()["start-gate"]
    assert 'run: bash tools/start_gate/start_gate.sh "${{ matrix.image }}"' in job
    assert "START_GATE_CHROOT: ${{ matrix.chroot }}" in job
    assert "START_GATE_ENGINE: docker" in job


def test_the_job_name_is_the_check_name_that_verify_checks_looks_for():
    assert "    name: start gate (${{ matrix.chroot }})\n" in _jobs()["start-gate"]


def test_the_negative_control_is_run_by_hand_and_only_by_hand():
    text = _text(NEGATIVE)
    assert re.search(r"^on:\n  workflow_dispatch:\n\n", text, re.M)
    assert not re.search(r"^\s+(?:pull_request|push|schedule|workflow_run):", text, re.M)


def test_no_job_of_the_negative_control_is_named_like_a_leg_of_the_gate():
    """``verify_checks.sh`` counts every check named ``start gate (...)``: the control must not
    leave one on the commit."""
    for workflow in WORKFLOW.parent.glob("*.yml"):
        if workflow == WORKFLOW:
            continue
        for job in re.findall(r"^    name: (.*)$", _text(workflow), re.M):
            assert not job.lower().startswith("start gate"), f"{workflow.name}: {job}"


def test_the_negative_control_runs_on_the_image_of_epel_10():
    job = _jobs(NEGATIVE)["negative-control"]
    assert "START_GATE_CHROOT: epel-10" in job
    assert "START_GATE_ENGINE: docker" in job
    assert "run: bash tools/start_gate/negative_control.sh quay.io/centos/centos:stream10 ." in job
    images = dict(re.findall(r"- chroot: (\S+)\n\s+image: (\S+)", _text()))
    assert "negative_control.sh " + images["epel-10"] + " " in job


def test_the_releasing_file_names_the_file_of_the_control():
    text = RELEASING.read_text(encoding="utf-8")
    assert ".github/workflows/negative-control.yml" in text
