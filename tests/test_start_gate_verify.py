# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

"""``tools/start_gate/verify_checks.sh``: the condition before a COPR build, checked by a machine.

The script reads the head of master, the chroots of the COPR project and the check runs of a commit
from two APIs. Here both are a local HTTP server that answers what the test says, so every way the
answer can be wrong (a red leg, a missing leg, a leg for a chroot the project has not, a project
with a chroot that has no leg, a commit that is not the head of master, an API that does not
answer) is run, and the script must end with a non-zero status.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest
from start_gate_helpers import GATE

SHA = "0123456789abcdef0123456789abcdef01234567"
CHROOTS = ["epel-10", "fedora-43", "fedora-44", "fedora-45", "fedora-rawhide"]
COPR_PATH = "/api_3/project/"
HEAD_PATH = "/repos/trensoft/hotrec/commits/master"
CHECKS_PATH = f"/repos/trensoft/hotrec/commits/{SHA}/check-runs"

pytestmark = pytest.mark.skipif(shutil.which("curl") is None, reason="curl is not installed")


def copr_answer(chroots=CHROOTS, arches=("x86_64",)):
    return {"chroot_repos": {f"{name}-{arch}": "https://x" for name in chroots for arch in arches}}


def run_of(chroot, status="completed", conclusion="success", app="github-actions"):
    return {
        "name": f"start gate ({chroot})",
        "status": status,
        "conclusion": conclusion,
        "app": {"slug": app},
    }


def checks_answer(runs):
    return {"total_count": len(runs), "check_runs": runs}


def all_green():
    return checks_answer([run_of(chroot) for chroot in CHROOTS])


class Server:
    def __init__(self):
        self.answers = {}
        # what the API answers when the query does not have filter=latest: GitHub then lists every
        # check run of the commit, the old runs of a re-run job too
        self.unfiltered = {}
        self.requests = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                owner.requests.append(self.path)
                path, _, query = self.path.partition("?")
                answers = owner.answers
                if "latest" not in parse_qs(query).get("filter", []):
                    answers = {**answers, **owner.unfiltered}
                status, body = answers.get(path, (404, {}))
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        threading.Thread(
            target=lambda: self.httpd.serve_forever(poll_interval=0.01), daemon=True
        ).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def api():
    server = Server()
    server.answers[COPR_PATH] = (200, copr_answer())
    server.answers[CHECKS_PATH] = (200, all_green())
    server.answers[HEAD_PATH] = (200, {"sha": SHA})
    yield server
    server.close()


def verify(api, sha=SHA, **env):
    full_env = {
        "PATH": "/usr/bin:/bin",
        "START_GATE_COPR_API": api.url + "/api_3",
        "START_GATE_GITHUB_API": api.url,
    }
    full_env.update(env)
    return subprocess.run(
        ["bash", str(GATE / "verify_checks.sh"), sha],
        env=full_env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_all_four_legs_green_is_a_pass(api):
    result = verify(api)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip().splitlines()[-1].startswith(f"VERIFY-CHECKS PASS {SHA}")
    for chroot in CHROOTS:
        assert chroot in result.stdout


def test_the_architectures_of_a_chroot_are_one_chroot(api):
    api.answers[COPR_PATH] = (200, copr_answer(arches=("x86_64", "aarch64")))
    assert verify(api).returncode == 0


@pytest.mark.parametrize(
    "bad",
    [
        run_of("fedora-43", conclusion="failure"),
        run_of("fedora-43", conclusion="cancelled"),
        run_of("fedora-43", conclusion="skipped"),
        run_of("fedora-43", conclusion="neutral"),
        run_of("fedora-43", conclusion=None),
        run_of("fedora-43", status="in_progress", conclusion=None),
        run_of("fedora-43", status="queued", conclusion=None),
        run_of("fedora-43", app="some-other-app"),
    ],
)
def test_a_leg_that_is_not_a_success_of_github_actions_fails(api, bad):
    runs = [bad if run["name"] == bad["name"] else run for run in all_green()["check_runs"]]
    api.answers[CHECKS_PATH] = (200, checks_answer(runs))
    result = verify(api)
    assert result.returncode == 1
    assert "VERIFY-CHECKS FAIL" in result.stdout
    assert "fedora-43" in result.stdout + result.stderr


def test_a_missing_leg_fails(api):
    runs = [run_of(chroot) for chroot in CHROOTS if chroot != "epel-10"]
    api.answers[CHECKS_PATH] = (200, checks_answer(runs))
    result = verify(api)
    assert result.returncode == 1
    assert "epel-10: 0 checks" in result.stderr


def test_no_check_at_all_fails(api):
    api.answers[CHECKS_PATH] = (200, checks_answer([]))
    assert verify(api).returncode == 1


def test_a_chroot_of_the_copr_project_with_no_leg_fails(api):
    api.answers[COPR_PATH] = (200, copr_answer(CHROOTS + ["fedora-46"]))
    result = verify(api)
    assert result.returncode == 1
    assert "fedora-46: 0 checks" in result.stderr


def test_a_leg_for_a_chroot_the_copr_project_has_not_fails(api):
    api.answers[COPR_PATH] = (200, copr_answer([c for c in CHROOTS if c != "fedora-43"]))
    result = verify(api)
    assert result.returncode == 1
    assert "fedora-43: a leg with no chroot in the COPR project" in result.stderr


def test_the_chroot_list_comes_from_the_copr_api_not_from_a_file(api, tmp_path):
    """A copy of the script run from another directory has no docs/RELEASING.md next to it: the
    answer is the same, because the chroots are not read from the tree."""
    copy = tmp_path / "verify_checks.sh"
    shutil.copy(GATE / "verify_checks.sh", copy)
    env = {
        "PATH": "/usr/bin:/bin",
        "START_GATE_COPR_API": api.url + "/api_3",
        "START_GATE_GITHUB_API": api.url,
    }
    result = subprocess.run(
        ["bash", str(copy), SHA], env=env, capture_output=True, text=True, timeout=60, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("which", ["copr", "github", "head"])
@pytest.mark.parametrize("status", [404, 500])
def test_an_api_that_answers_with_an_error_fails(api, which, status):
    """The status counts, not the body: an error page that happens to look like an answer (a proxy,
    a cache) must not be read as one."""
    path, good = {
        "copr": (COPR_PATH, copr_answer()),
        "github": (CHECKS_PATH, all_green()),
        "head": (HEAD_PATH, {"sha": SHA}),
    }[which]
    api.answers[path] = (status, good)
    result = verify(api)
    assert result.returncode == 1
    assert "VERIFY-CHECKS FAIL" in result.stdout


@pytest.mark.parametrize("which", ["copr", "github"])
def test_an_api_that_is_not_there_fails(api, which):
    # the GitHub API answers for the head of master and for the checks: both are on that address
    key = "START_GATE_COPR_API" if which == "copr" else "START_GATE_GITHUB_API"
    result = verify(api, **{key: "http://127.0.0.1:1"})
    assert result.returncode == 1
    assert "VERIFY-CHECKS FAIL" in result.stdout


@pytest.mark.parametrize("body", [{}, {"chroot_repos": {}}, {"chroot_repos": ["epel-10-x86_64"]}])
def test_a_copr_answer_with_no_chroots_fails(api, body):
    api.answers[COPR_PATH] = (200, body)
    assert verify(api).returncode == 1


def test_an_incomplete_list_of_checks_fails(api):
    answer = all_green()
    answer["total_count"] = 130
    api.answers[CHECKS_PATH] = (200, answer)
    assert verify(api).returncode == 1


def test_two_checks_of_one_name_fail(api):
    api.answers[CHECKS_PATH] = (200, checks_answer(all_green()["check_runs"] + [run_of("epel-10")]))
    assert verify(api).returncode == 1


@pytest.mark.parametrize("sha", ["", "main", "v0.1.7", SHA[:7], SHA.upper(), SHA + "0"])
def test_only_a_full_commit_sha_is_accepted(api, sha):
    assert verify(api, sha=sha).returncode == 2


def test_the_token_is_sent_when_there_is_one(api):
    seen = []
    original = api.httpd.RequestHandlerClass.do_GET

    def spy(handler):
        seen.append(handler.headers.get("Authorization"))
        return original(handler)

    api.httpd.RequestHandlerClass.do_GET = spy
    verify(api, GITHUB_TOKEN="t0ken")
    assert "Bearer t0ken" in seen


# ---- the commit must be the head of master (COPR builds the head) -----------------------------


def test_a_commit_that_is_not_the_head_of_master_fails_even_when_all_legs_are_green(api):
    other = "f" * 40
    api.answers[HEAD_PATH] = (200, {"sha": other})
    result = verify(api)
    assert result.returncode == 1
    assert f"the head of the branch is {other}, not {SHA}" in result.stderr
    assert "VERIFY-CHECKS FAIL" in result.stdout


@pytest.mark.parametrize(
    "body", [{}, {"sha": ""}, {"sha": "main"}, {"sha": SHA[:7]}, {"sha": None}]
)
def test_an_answer_for_the_head_without_a_commit_sha_fails(api, body):
    api.answers[HEAD_PATH] = (200, body)
    assert verify(api).returncode == 1


def test_the_branch_can_be_changed_for_the_tests_of_the_script(api):
    api.answers["/repos/trensoft/hotrec/commits/other"] = (200, {"sha": SHA})
    api.answers[HEAD_PATH] = (200, {"sha": "f" * 40})
    assert verify(api, START_GATE_BRANCH="other").returncode == 0


def test_the_pass_line_says_it_was_the_head(api):
    result = verify(api)
    assert f"head of the branch: {SHA}" in result.stdout
    assert "the head of master" in result.stdout.strip().splitlines()[-1]


def test_it_asks_for_the_copr_project_hotrec_of_trensoft_and_the_repository_hotrec(api):
    assert verify(api).returncode == 0
    assert f"{COPR_PATH}?ownername=trensoft&projectname=hotrec" in api.requests
    assert HEAD_PATH in api.requests
    assert any(path.startswith(CHECKS_PATH) for path in api.requests)


# ---- only the latest run of a check counts (a re-run job leaves its old run behind) -----------


def test_the_check_runs_are_asked_for_with_filter_latest_and_a_full_page(api):
    """Without ``filter=latest`` GitHub lists the old runs of a re-run job as well, a red run that
    was fixed by the re-run among them: the gate would be red for ever (or, with the filter on a
    page that is too small, a leg would be missing)."""
    assert verify(api).returncode == 0
    asked = [urlsplit(path) for path in api.requests if urlsplit(path).path == CHECKS_PATH]
    assert len(asked) == 1
    query = parse_qs(asked[0].query)
    assert query["filter"] == ["latest"]
    assert query["per_page"] == ["100"]


def test_a_re_run_leg_is_read_as_its_latest_run(api):
    """The leg of fedora-43 failed and was re-run green. GitHub lists both runs unless it is asked
    for the latest: the script must ask, and so see one check for the leg."""
    stale = run_of("fedora-43", conclusion="failure")
    api.unfiltered[CHECKS_PATH] = (200, checks_answer(all_green()["check_runs"] + [stale]))
    result = verify(api)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip().splitlines()[-1].startswith(f"VERIFY-CHECKS PASS {SHA}")


@pytest.mark.parametrize("filter_", ["all", ""])
def test_the_stand_in_lists_the_old_runs_when_the_filter_is_not_latest(api, filter_):
    """The control of the test above: asked without ``filter=latest`` the stand-in answers with two
    checks for the leg, so the test above cannot pass for another reason."""
    stale = run_of("fedora-43", conclusion="failure")
    api.unfiltered[CHECKS_PATH] = (200, checks_answer(all_green()["check_runs"] + [stale]))
    # ask by hand the way a script without the filter would
    url = f"{api.url}{CHECKS_PATH}?filter={filter_}&per_page=100"
    body = json.load(urllib.request.urlopen(url, timeout=10))  # noqa: S310
    names = [run["name"] for run in body["check_runs"]]
    assert names.count("start gate (fedora-43)") == 2
