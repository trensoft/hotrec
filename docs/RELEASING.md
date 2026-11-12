<!--
SPDX-FileCopyrightText: 2026 TrenSoft
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Releasing

What stands here is the rule of the start gate and how it is proved. The rest of the release work
(the version bump in `pyproject.toml`, `hotrec/__init__.py`, the spec, the metainfo and the manual
page, which `tests/test_packaging.py` keeps equal; the tag; the report) is not written down in this
file yet.
`[H]` marks background knowledge, or a claim about a server that this repository cannot show.

## The COPR project and what it builds

The facts below are those of the COPR API (`/api_3/package/list`, `/api_3/project/`), read on
2026-11-12; they are checked again by `tools/start_gate/verify_checks.sh` every time it runs.

- The project is `trensoft/hotrec`. It has two packages, `hotrec` and `gpu-screen-recorder`. Both are
  built from `https://github.com/trensoft/hotrec.git` with the `make_srpm` method, which runs
  `.copr/Makefile` (the spec is `packaging/fedora/hotrec.spec`, and `gpu-screen-recorder.spec`).
- The committish of both packages is empty: a build takes the **head of the default branch**
  (`master`) at the moment it starts. A tag is not built.
- The chroots are `epel-10-x86_64`, `fedora-43-x86_64`, `fedora-44-x86_64`, `fedora-45-x86_64` and
  `fedora-rawhide-x86_64`.
- The `hotrec` package has `auto_rebuild: true` in the API. Whether the GitHub repository has the
  webhook that would start a build at every push to `master` is not visible from here: it needs the
  rights of the repository's admin. The maintainer's word is that there is none and the build is
  started by hand [H]. If there is one, a push to `master` is built before the gate can have run, and
  the rule below cannot be kept: that is a decision for the maintainer, and this file has to say so.
  What the repository and the COPR API show, and agree with that word: the repository has no
  `.packit.yaml`, and no workflow starts a COPR build (`.github/workflows/ci.yml` has no COPR step);
  all 12 builds of the project (`/api_3/build/list/`, read on 2026-11-12: 9 of `hotrec` and 3 of
  `gpu-screen-recorder`) have the submitter `trensoft`, that is, they were started by that account.
  A build started by a webhook has no submitter: the builds of `slideshow-lock` that a tag started
  (1.0.11, 1.0.12) have the submitter `None`, and the one that was started by hand (1.0.10-2) has
  `trensoft`. That is a measurement of the past builds, not of what the webhook would do tomorrow.

## The start gate

Until now nothing ran the program as it is installed: the tests run from a checkout with the toolkit
and the desktop replaced by fakes, and the build of an RPM only runs `%pyproject_check_import` and
validates the data files. A package that builds and installs can still fail at the first login. The
start gate runs the start of the installed program, in a clean container of every COPR chroot.

`tools/start_gate/start_gate.sh IMAGE [TREE]` (with `START_GATE_CHROOT=<chroot>`) does it in two
containers, podman or docker:

1. **Stage 1, `build.sh`.** The source RPM is made by `.copr/Makefile` from the tree (the file COPR
   runs, `git archive` of `HEAD`), `dnf builddep`, then `rpmbuild --rebuild`: the RPMs `hotrec` and
   `hotrec-gnome-shell-extension`. When `rpmbuild` ends with 11 (`%generate_buildrequires` names more
   build requirements, on EL10 in two rounds), they are installed and it runs again, at most 5 rounds,
   then the stage fails.
2. **Stage 2, `check.sh`**, in a fresh container with neither the tree nor the build tools: `dnf
   install` of both RPMs **without weak dependencies**, then
   - `rpm -q` for both packages (an image without `rpm` fails; the step is not left out);
   - `probe_installed.py`, steps `version` (the installed version is the RPM's, from the system
     site-packages), `import` (every module imports; GTK 3 and an AppIndicator typelib load), `cli`
     (`hotrec --version`, `hotrec status` ends with 1), `catalog` (a translation catalog of the RPM
     is found and used) and `tools` (`gpu-screen-recorder` has no missing library, `ffmpeg` runs and
     has the MP3 encoder, `pactl` and `notify-send` run);
   - `probe_session.py`, the real `hotrec autostart` of the installed package in a headless GNOME
     Shell session (see below), steps `shell`, `loaded`, `autostart`, `extension`, `dot`, `windows`,
     `single` and `quit`.

The session of `probe_session.py` is made of real parts: the `gnome-shell --headless` of the image
(with its mutter, no GPU, Wayland), a private D-Bus session bus on which only the dconf service and
the Shell's extension service can be started, and a private "system" bus with `fake_login1.py` as
logind. `fake_desktop.py` stands in for the two services that a real session gets from the
AppIndicator extension and from the notification daemon (the tray watcher and the notification
server) and writes what it is told into a log. Then:

| Step | What has to be true |
| --- | --- |
| `shell` | The Shell answers. |
| `loaded` | The Shell knows the extension of the package: loaded, not out of date for this Shell (state 4), not broken (state 3). |
| `autostart` | `hotrec autostart` runs and still runs a second after the dot registered; the notification "Keyboard shortcuts are set" arrives; `hotrec shortcuts status` reads the six shortcuts back from dconf. |
| `extension` | The Shell has switched the extension on (state ENABLED), and Hotrec said so in the words for a Shell that knows the extension (no "log out and in"); the Shell logged no error about it. |
| `dot` | The dot is registered with the tray watcher, and its menu is the menu of the resident dot, the keys of the shortcuts in its rows. |
| `windows` | "Settings..." and "About" are clicked: the program keeps running and logs no traceback. |
| `single` | A second `hotrec autostart` ends at once with 0 and makes no second dot. |
| `quit` | The menu row "Quit" ends the first one with status 0. |

A step that needs the result of another does not run when that one failed, and says so (`FAIL not
run`): `loaded` and `autostart` need `shell`, `extension` and `dot` need `autostart`, `windows`,
`single` and `quit` need `dot`. The others run: a Shell that finds the extension out of date still
has a dot.

What the gate adds to the image, and why: the COPR repository of the project, for the single package
`gpu-screen-recorder` (`includepkgs`), because Hotrec requires it and only that project has it;
`dbus-daemon` and `dconf`, two parts of a GNOME session that nothing of the program requires and the
session probe needs. On EL10 EPEL 10 and CRB are enabled, the way the chroot `epel-10` has them.

Start gate chroots: `epel-10`, `fedora-43`, `fedora-44`, `fedora-45`, `fedora-rawhide` (the list of
the COPR project; `.github/workflows/start-gate.yml` has one leg for each).

## Before a COPR build of `master`: the condition

No build of `hotrec` is started in the COPR project unless all of these hold:

1. The team gate is green for the same tree (the reviewers and the QA run; a gate for another tree
   does not count).
2. The start gate is green on the commit that the build will take, on every leg of the matrix,
   `epel-10` first. A leg that did not run is not green: if one chroot did not run, there is no build.
   The proof is the output of `tools/start_gate/verify_checks.sh <sha>` (`VERIFY-CHECKS PASS`), run
   for that commit before the build. It is the required step before the build, and with no output of
   it there is no build.

`verify_checks.sh` makes sure of four things: the commit is the **head of `master` now** (a commit
pushed after the gate would be built without it); the chroot list of the COPR project is read from the
COPR API, not from a file; every chroot has exactly one `start gate (<chroot>)` check of GitHub
Actions, completed with `success`; and a leg for a chroot that the project does not have fails too. An
API that cannot be read is a failure.

The workflow runs on pull requests and on pushes to `master`: the push is the run on the commit that is
built. That a push to `master` with a red or missing check cannot be built at all (a required status
check of the branch protection) is a setting of the repository, for the maintainer's side; this file
does not make it. The API shows that `master` is protected; which checks are required is not visible
without the rights of an admin [H].

## The negative control

A gate that cannot fail is not a gate. `tools/start_gate/negative_control.sh IMAGE TREE` copies the
tree, breaks the start of the dot in the copy (`AppIndicator.IndicatorStatus.ACTIVE` becomes
`ACTIVEX`: the module imports and the program dies at the dot, the kind of break an import check does
not see), runs the gate on it, and is green only when the output of stage 2 shows the break and nothing
else, each as a line of its own: `START-GATE rpm PASS` twice and `version`, `import`, `cli`, `catalog`,
`tools`, `shell` and `loaded` PASS (every step before the dot), `START-GATE autostart FAIL ...
AttributeError: ... ACTIVEX` (the step `autostart` fails with the error that the break made), and
`START-GATE RESULT FAIL`. A gate that passes is soft; a gate that fails for another reason (no network,
a build error, a step before the dot, an `autostart` that fails with another error) proves nothing, and
that is not a pass either. The workflow is `.github/workflows/negative-control.yml`, a file of its own,
run by hand (`Run workflow`) and only by hand, on the image of `epel-10`: it leaves no check named
`start gate (<chroot>)` on the commit, so `verify_checks.sh` has nothing extra to count, and
`start-gate.yml` has no run by hand and no job with an `if`. The control breaks the tree of the ref it
runs on, so there is no old tree to pin (the slideshow-lock control runs on an old release and is pinned
by the SHA of its commit).

## What the gate does not measure

- A recording. `gpu-screen-recorder` needs a GPU and a screen cast portal, and refuses to run as root
  (the gate checks that it is linked, not that it records). `hotrec video-audio` and the other modes
  are not started; no audio is recorded; the area selector (`hotrec select-region`) is not run.
- Whether the dot is **drawn**. That is the Shell's AppIndicator extension, which is not installed
  here (the gate takes its place); nor is the red dot of the Hotrec extension seen drawn over a video.
  That the Shell loads and switches on the extension is measured, that it draws is not.
- Whether the windows "Settings..." and "About" **appear**: a client cannot ask the Shell for its
  windows. That the click runs the code and the program survives is measured.
- The weak dependencies (`Recommends`), a GNOME session of a real user (a real logind, `gdm`), a real
  keyboard shortcut press, a second monitor, Intel/AMD/NVIDIA graphics.
- Everything on aarch64: the COPR project has only x86_64 chroots.
