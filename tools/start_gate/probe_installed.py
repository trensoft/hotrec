# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

"""Start gate, the first probe: the INSTALLED package, without a desktop session.

version   the installed hotrec has the version the RPM was built with, ``hotrec.__version__`` says
          the same, and the package is the copy in the system site-packages, not a checkout;
import    every module of the package imports from there, and the toolkit of the top bar dot loads
          (``indicator._load_toolkit``: GTK 3 and an AppIndicator typelib, the part that is not
          imported until the dot starts);
cli       the installed ``hotrec`` command runs: ``--version``, and ``status`` ends with 1 and says
          "not recording" (it reads the state directory, which it makes);
catalog   a translation catalog of the RPM is found and used (``i18n.setup``, ``LANGUAGE=hu``);
tools     the programs Hotrec runs are there and linked: gpu-screen-recorder with no missing
          library (it refuses to run as root, so it is not started), ffmpeg runs and has the MP3
          encoder the sound-only mode needs, ``pactl`` and ``notify-send`` run.

usage: python3 -I probe_installed.py EXPECTED_VERSION
Prints one line per step, ``START-GATE <step> PASS|FAIL <detail>``; exits 1 when a step failed.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import os
import pkgutil
import shutil
import subprocess
import sys
import tempfile


def _run(command, **kwargs):
    return subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        **kwargs,
    )


def _clean_env(tmp):
    """A home and a runtime directory of its own: the command makes its state directory there."""
    run_dir = os.path.join(tmp, "run")
    os.makedirs(run_dir, mode=0o700, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k not in ("LANGUAGE", "LC_ALL", "LC_MESSAGES")}
    env.update(HOME=tmp, XDG_RUNTIME_DIR=run_dir, LANG="C")
    return env


def step_version(expected: str) -> str:
    version = importlib.metadata.version("hotrec")
    if version != expected:
        raise AssertionError(f"installed version {version}, the RPM has {expected}")
    package = importlib.import_module("hotrec")
    if package.__version__ != expected:
        raise AssertionError(f"hotrec.__version__ is {package.__version__}, the RPM has {expected}")
    path = os.path.realpath(package.__file__)
    if not path.startswith(os.path.realpath(sys.base_prefix) + os.sep):
        raise AssertionError(f"hotrec is loaded from {path}, not from {sys.base_prefix}")
    return f"version {version} from {path}"


def step_import() -> str:
    package = importlib.import_module("hotrec")
    names = sorted(info.name for info in pkgutil.iter_modules(package.__path__))
    if len(names) < 10:
        raise AssertionError(f"only {len(names)} modules found in {package.__path__}: {names}")
    for name in names:
        importlib.import_module(f"hotrec.{name}")
    indicator = importlib.import_module("hotrec.indicator")
    gtk, glib, app_indicator = indicator._load_toolkit()
    if gtk.get_major_version() != 3:
        raise AssertionError(f"Gtk {gtk.get_major_version()}, a GTK 3 program needs GTK 3")
    return (
        f"{len(names)} modules import; Gtk {gtk.get_major_version()}.{gtk.get_minor_version()}, "
        f"{app_indicator.__name__}, GLib {glib.MAJOR_VERSION}.{glib.MINOR_VERSION}"
    )


def step_cli(expected: str) -> str:
    command = shutil.which("hotrec")
    if command != "/usr/bin/hotrec":
        raise AssertionError(
            f"the hotrec command is {command!r}, not the installed /usr/bin/hotrec"
        )
    with tempfile.TemporaryDirectory() as tmp:
        env = _clean_env(tmp)
        shown = _run([command, "--version"], env=env)
        if shown.returncode != 0 or shown.stdout.strip() != f"hotrec {expected}":
            raise AssertionError(
                f"hotrec --version: status {shown.returncode}, "
                f"{shown.stdout!r} {shown.stderr[-200:]!r}"
            )
        status = _run([command, "status"], env=env)
        if status.returncode != 1 or "not recording" not in status.stdout:
            raise AssertionError(
                f"hotrec status: status {status.returncode}, "
                f"{status.stdout!r} {status.stderr[-200:]!r}"
            )
    return f"{command}: --version says hotrec {expected}, status ends with 1 (not recording)"


def step_catalog() -> str:
    import gettext

    os.environ["LANGUAGE"] = "hu"
    os.environ.pop("HOTREC_LOCALEDIR", None)
    from hotrec import APP_ID, i18n

    status = i18n.setup()
    if not status.catalogs:
        raise AssertionError(f"no catalog found for LANGUAGE=hu under {status.localedir}")
    wanted = f"/hu/LC_MESSAGES/{APP_ID}.mo"
    if not any(path.endswith(wanted) for path in status.catalogs):
        raise AssertionError(f"the catalogs are {status.catalogs}, none ends with {wanted}")
    text = gettext.gettext("Stop and save")
    if not text or text == "Stop and save":
        raise AssertionError(f"'Stop and save' is not translated by the catalog: {text!r}")
    return f"{len(status.catalogs)} catalog from {status.localedir}, 'Stop and save' -> {text!r}"


def step_tools() -> str:
    found = []
    gsr = shutil.which("gpu-screen-recorder")
    if not gsr:
        raise AssertionError("gpu-screen-recorder is not installed")
    if not shutil.which("ldd"):
        raise AssertionError(
            "there is no ldd in the image: the libraries of gpu-screen-recorder cannot be checked"
        )
    linked = _run(["ldd", gsr])
    missing = [line.strip() for line in linked.stdout.splitlines() if "not found" in line]
    if linked.returncode != 0 or missing:
        raise AssertionError(f"ldd {gsr}: status {linked.returncode}, not found: {missing}")
    found.append("gpu-screen-recorder linked")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise AssertionError("no ffmpeg: the sound-only mode and the area cut need it")
    encoders = _run([ffmpeg, "-hide_banner", "-encoders"])
    if encoders.returncode != 0 or "libmp3lame" not in encoders.stdout:
        raise AssertionError(
            f"ffmpeg -encoders: status {encoders.returncode}, libmp3lame "
            f"{'present' if 'libmp3lame' in encoders.stdout else 'missing'}: "
            f"{encoders.stderr[-200:]!r}"
        )
    found.append("ffmpeg has libmp3lame")
    for name in ("pactl", "notify-send"):
        path = shutil.which(name)
        if not path:
            raise AssertionError(f"{name} is not installed")
        answer = _run([path, "--version"])
        if answer.returncode != 0:
            raise AssertionError(
                f"{name} --version: status {answer.returncode}: {answer.stderr[-200:]!r}"
            )
        found.append(f"{name} runs")
    return ", ".join(found)


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    expected = sys.argv[1]
    steps = (
        ("version", lambda: step_version(expected)),
        ("import", step_import),
        ("cli", lambda: step_cli(expected)),
        ("catalog", step_catalog),
        ("tools", step_tools),
    )
    failed = False
    for name, run in steps:
        try:
            print(f"START-GATE {name} PASS {run()}", flush=True)
        except Exception as exc:  # every kind of failure is a failed step
            failed = True
            print(f"START-GATE {name} FAIL {type(exc).__name__}: {exc}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
