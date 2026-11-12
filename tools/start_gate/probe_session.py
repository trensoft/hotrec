# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

"""Start gate, the second probe: the real ``hotrec autostart`` of the installed package, in a
headless GNOME Shell session.

A container has no desktop, so the probe makes one out of the real parts: a private D-Bus session
bus (with the dconf service and the Shell's extension service activatable) and a private "system"
bus with ``fake_login1.py`` as logind; the real ``gnome-shell --headless`` of the image on them (the
Shell and mutter run with no GPU, the window system is Wayland); and ``fake_desktop.py`` for the two
services that the AppIndicator extension and a notification daemon are in a real session (the tray
watcher and the notification server). What it does then is what a login does:

shell      the Shell is up;
loaded     it knows the extension of the package: loaded, not out of date for this Shell, not
           broken;
autostart  ``hotrec autostart`` runs and the notification "Keyboard shortcuts are set" arrives, the
           six shortcuts are in dconf (``hotrec shortcuts status`` reads them back);
extension  the Shell has switched the extension on (state ENABLED), and Hotrec said so in the
           words for a Shell that knows it ("on", not "log out and in");
dot        the top bar dot is registered with the tray watcher, and its menu is the menu of the
           resident dot, with the keys of the shortcuts in the rows;
windows    "Settings..." and "About" are clicked: the program keeps running and logs no traceback;
single     a second ``hotrec autostart`` ends at once with 0 and makes no second dot;
quit       the menu row "Quit" ends the first one with status 0.

What it cannot do: record (``gpu-screen-recorder`` needs a GPU and refuses to run as root), see the
dot drawn (it is the Shell's AppIndicator extension, not installed here), or see the red dot of the
Hotrec extension drawn over a video.

usage: python3 -I probe_session.py [--timeout SECONDS]
Prints ``START-GATE <step> PASS|FAIL <detail>`` per step; exits 1 on any FAIL. After a failure the
logs of the Shell and of the program are printed.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
UUID = "hotrec-dot@trensoft.github.io"
# org.gnome.Shell.Extensions: ENABLED, DISABLED, INITIALIZED, DISABLING, ENABLING are a loaded and
# usable extension; ERROR (3), OUT_OF_DATE (4), DOWNLOADING (5) and UNINSTALLED (99) are not.
STATE_ENABLED = 1
LOADED_STATES = {1, 2, 6, 7, 8}
BUS_CONFIG = """<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-Bus Bus Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
  <type>session</type>
  <listen>unix:path={path}</listen>
  <auth>EXTERNAL</auth>
  {servicedir}
  <policy context="default">
    <allow send_destination="*" eavesdrop="true"/>
    <allow eavesdrop="true"/>
    <allow own="*"/>
  </policy>
</busconfig>
"""
# Only these two services can be started by the bus: the store of the settings, and the service that
# answers the Shell's questions about its extensions. Nothing else of the installed GNOME packages.
SERVICES = ("ca.desrt.dconf.service", "org.gnome.Shell.Extensions.service")
SERVICE_DIR = "/usr/share/dbus-1/services"
# The menu of the resident dot, with the keys as the shortcuts have them after `hotrec autostart`.
# (label, enabled) in order.
MENU = [
    ("Record screen and sound (Ctrl+Shift+F9)", True),
    ("Record screen only (Ctrl+Shift+F10)", True),
    ("Record sound only (Ctrl+Shift+F11)", True),
    ("Record area and sound (Ctrl+Shift+F7)", True),
    ("Record area only (Ctrl+Shift+F8)", True),
    ("Pause (Ctrl+Shift+F12)", False),
    ("Stop and save", False),
    ("Settings…", True),
    ("About", True),
    ("Quit", True),
]
KEYS = (
    "Ctrl+Shift+F9",
    "Ctrl+Shift+F10",
    "Ctrl+Shift+F11",
    "Ctrl+Shift+F12",
    "Ctrl+Shift+F7",
    "Ctrl+Shift+F8",
)


class Failed(Exception):
    pass


class Session:
    def __init__(self, tmp: str, timeout: float) -> None:
        self.tmp = tmp
        self.timeout = timeout
        self.children: list[subprocess.Popen] = []
        self.home = os.path.join(tmp, "home")
        self.run_dir = os.path.join(tmp, "run")
        os.makedirs(self.home)
        os.makedirs(self.run_dir, mode=0o700)
        self.session_bus = ""
        self.system_bus = ""
        self.desktop_log = os.path.join(tmp, "desktop.log")
        self.shell_log = os.path.join(tmp, "shell.log")
        self.program_log = os.path.join(tmp, "autostart.log")
        self.program: subprocess.Popen | None = None
        self.item = ""
        self.shell_version = ""
        self.menu_path = ""
        self.rows: dict = {}

    # -- the session ---------------------------------------------------------------------------

    def env(self) -> dict:
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("DISPLAY", "LANGUAGE", "LC_ALL", "LC_MESSAGES")
        }
        env.update(
            HOME=self.home,
            XDG_RUNTIME_DIR=self.run_dir,
            LANG="C",
            DBUS_SESSION_BUS_ADDRESS=self.session_bus,
            DBUS_SYSTEM_BUS_ADDRESS=self.system_bus,
            WAYLAND_DISPLAY="wl-gate",
            GDK_BACKEND="wayland",
            XDG_SESSION_TYPE="wayland",
            XDG_CURRENT_DESKTOP="GNOME",
            LIBGL_ALWAYS_SOFTWARE="1",
        )
        return env

    def spawn(self, command: list, log: str, **kwargs) -> subprocess.Popen:
        handle = open(log, "ab")
        child = subprocess.Popen(
            command,
            env=kwargs.pop("env", None) or self.env(),
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=subprocess.STDOUT,
            **kwargs,
        )
        self.children.append(child)
        return child

    def start_bus(self, name: str, services: bool) -> str:
        path = os.path.join(self.run_dir, f"{name}.sock")
        service_dir = ""
        if services:
            target = os.path.join(self.tmp, "services")
            os.makedirs(target)
            for service in SERVICES:
                source = os.path.join(SERVICE_DIR, service)
                if not os.path.exists(source):
                    raise Failed(f"{source} is not installed: the {name} bus cannot start it")
                shutil.copy(source, target)
            service_dir = f"<servicedir>{target}</servicedir>"
        config = os.path.join(self.tmp, f"{name}.conf")
        with open(config, "w", encoding="utf-8") as fh:
            fh.write(BUS_CONFIG.format(path=path, servicedir=service_dir))
        self.spawn(
            ["dbus-daemon", "--nofork", f"--config-file={config}"],
            os.path.join(self.tmp, f"{name}-bus.log"),
            # what the bus starts (dconf, the extension service) has the environment of the bus
            env={k: v for k, v in self.env().items() if v},
        )
        for _ in range(100):
            if os.path.exists(path):
                return f"unix:path={path}"
            time.sleep(0.1)
        raise Failed(f"the {name} bus did not come up")

    def gdbus(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["gdbus", "call", "--session", *args],
            env=self.env(),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    def wait_for(self, what: str, check, timeout: float | None = None):
        deadline = time.monotonic() + (timeout or self.timeout)
        while time.monotonic() < deadline:
            value = check()
            if value:
                return value
            time.sleep(0.25)
        raise Failed(f"{what}: not after {timeout or self.timeout:.0f} s")

    @staticmethod
    def _read(path: str) -> str:
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                return fh.read()
        except OSError:
            return ""

    def desktop(self) -> str:
        return self._read(self.desktop_log)

    def extension_state(self) -> tuple[int | None, str]:
        answer = self.gdbus(
            "--dest",
            "org.gnome.Shell.Extensions",
            "--object-path",
            "/org/gnome/Shell/Extensions",
            "--method",
            "org.gnome.Shell.Extensions.GetExtensionInfo",
            UUID,
        )
        match = re.search(r"'state': <(?:double |uint32 |int32 )?(\d+)", answer.stdout)
        if answer.returncode != 0 or not match:
            return None, (answer.stdout + answer.stderr).strip()[:300]
        return int(match.group(1)), answer.stdout

    def hotrec(self, *args: str, timeout: float = 30) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["hotrec", *args],
            env=self.env(),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    # -- the steps -----------------------------------------------------------------------------

    def step_shell(self) -> str:
        self.session_bus = self.start_bus("session", services=True)
        self.system_bus = self.start_bus("system", services=False)
        login = self.spawn(
            [sys.executable, "-W", "ignore", os.path.join(HERE, "fake_login1.py")],
            os.path.join(self.tmp, "login1.log"),
            env={**self.env(), "DBUS_SESSION_BUS_ADDRESS": self.system_bus},
        )
        fake_log = os.path.join(self.tmp, "fake-desktop.log")
        self.spawn(
            [
                sys.executable,
                "-W",
                "ignore",
                os.path.join(HERE, "fake_desktop.py"),
                self.desktop_log,
            ],
            fake_log,
        )
        self.wait_for(
            "the fake desktop services are not up",
            lambda: "fake-desktop up" in self._read(fake_log),
            20,
        )
        if login.poll() is not None:
            raise Failed("fake_login1.py ended at once")
        self.spawn(
            [
                "gnome-shell",
                "--headless",
                "--wayland",
                "--no-x11",
                "--virtual-monitor",
                "1024x768",
                "--wayland-display",
                "wl-gate",
            ],
            self.shell_log,
        )

        def version() -> str:
            answer = self.gdbus(
                "--dest",
                "org.gnome.Shell",
                "--object-path",
                "/org/gnome/Shell",
                "--method",
                "org.freedesktop.DBus.Properties.Get",
                "org.gnome.Shell",
                "ShellVersion",
            )
            match = re.search(r"'([^']+)'", answer.stdout)
            return match.group(1) if answer.returncode == 0 and match else ""

        self.shell_version = self.wait_for("GNOME Shell does not answer", version, 90)
        return f"GNOME Shell {self.shell_version} is up"

    def step_loaded(self) -> str:
        """The Shell scanned the directory of the package and loaded the metadata: the extension is
        known, and not out of date for this Shell (state 4) or broken."""
        try:
            state, text = self.wait_for("the Shell does not know the extension", self._known, 60)
        except Failed as exc:
            raise Failed(
                f"{exc}; the answer of GetExtensionInfo: {self.extension_state()[1]!r}"
            ) from None
        if state not in LOADED_STATES:
            raise Failed(
                f"GNOME Shell {self.shell_version} has the extension in state {state}, "
                f"not a loaded one: {text[:300]}"
            )
        return f"GNOME Shell {self.shell_version} knows {UUID}, state {state}"

    def _known(self):
        state, text = self.extension_state()
        return (state, text) if state is not None else None

    def step_autostart(self) -> str:
        self.program = self.spawn(["hotrec", "autostart"], self.program_log)
        self.wait_for(
            "the dot is not registered",
            lambda: self._registered() or self._program_ended(),
        )
        time.sleep(1)  # a program that dies right after it registered the dot is not a start
        if self.program.poll() is not None:
            tail = self._read(self.program_log)[-600:]
            raise Failed(
                f"hotrec autostart ended with status {self.program.returncode} at its start: "
                f"{tail!r}"
            )
        desktop = self.desktop()
        if "Keyboard shortcuts are set" not in desktop:
            raise Failed(
                "no notification 'Keyboard shortcuts are set'; the desktop log:\n" + desktop
            )
        status = self.hotrec("shortcuts", "status")
        lines = status.stdout.splitlines()
        if status.returncode != 0 or len(lines) != len(KEYS):
            raise Failed(
                f"hotrec shortcuts status: status {status.returncode}, "
                f"{status.stdout!r} {status.stderr[-200:]!r}"
            )
        for keys in KEYS:
            row = [line for line in lines if line.startswith(keys)]
            if len(row) != 1 or "not set" in row[0] or not row[0].split()[-2].endswith("hotrec"):
                raise Failed(f"the shortcut {keys} is not set to hotrec: {row}")
        return (
            "notification 'Keyboard shortcuts are set'; 6 shortcuts read back from dconf: "
            + "; ".join(line.split()[0] for line in lines)
        )

    def _registered(self) -> str:
        for line in self.desktop().splitlines():
            if line.startswith("ITEM-REGISTERED "):
                return line.split()[1]
        return ""

    def _program_ended(self) -> bool:
        return self.program is not None and self.program.poll() is not None

    def step_extension(self) -> str:
        def enabled():
            state, _text = self.extension_state()
            return state == STATE_ENABLED

        try:
            self.wait_for("the Shell does not enable the extension", enabled, 30)
        except Failed:
            state, text = self.extension_state()
            raise Failed(
                f"the extension is in state {state}, not ENABLED (1): {text[:300]}"
            ) from None
        notes = [line for line in self.desktop().splitlines() if "blinking red dot" in line]
        if len(notes) != 1:
            raise Failed(
                f"expected one notification about the extension, found {len(notes)}: {notes}"
            )
        if "log out" in notes[0]:
            raise Failed("Hotrec did not see that the Shell knows the extension: " + notes[0])
        problems = [
            line.strip()[:200]
            for line in self._read(self.shell_log).splitlines()
            if "hotrec" in line.lower() and re.search(r"error|critical|exception", line, re.I)
        ]
        if problems:
            raise Failed("the Shell logged errors about the extension: " + " | ".join(problems[:3]))
        return (
            "the Shell switched the extension on (ENABLED); the notification says it is on, "
            "with no log out"
        )

    def _connection(self):
        import gi

        gi.require_version("Gio", "2.0")
        from gi.repository import Gio

        flags = (
            Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
            | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION
        )
        return Gio.DBusConnection.new_for_address_sync(self.session_bus, flags, None, None)

    def _call(self, conn, path: str, interface: str, method: str, args, signature: str):
        from gi.repository import Gio, GLib

        bus_name = self.item.split("/", 1)[0]
        return conn.call_sync(
            bus_name,
            path,
            interface,
            method,
            GLib.Variant(signature, args) if args is not None else None,
            None,
            Gio.DBusCallFlags.NONE,
            10000,
            None,
        )

    def _menu(self, conn) -> tuple[str, dict]:
        """The menu of the dot over D-Bus, as the tray gets it: ``{label: (id, enabled)}``."""
        path = "/" + self.item.split("/", 1)[1]
        got = self._call(
            conn,
            path,
            "org.freedesktop.DBus.Properties",
            "Get",
            ("org.kde.StatusNotifierItem", "Menu"),
            "(ss)",
        )
        menu_path = got.unpack()[0]
        layout = self._call(
            conn, menu_path, "com.canonical.dbusmenu", "GetLayout", (0, -1, []), "(iias)"
        )
        rows: dict = {}

        def walk(node):
            node_id, props, kids = node
            if "label" in props:
                rows[props["label"]] = (node_id, props.get("enabled", True))
            for kid in kids:
                walk(kid)

        walk(layout.unpack()[1])
        return menu_path, rows

    def _click(self, conn, menu_path: str, node_id: int) -> None:
        from gi.repository import GLib

        self._call(
            conn,
            menu_path,
            "com.canonical.dbusmenu",
            "Event",
            (node_id, "clicked", GLib.Variant("i", 0), 0),
            "(isvu)",
        )

    def step_dot(self) -> str:
        self.item = self._registered()
        if not self.item:
            raise Failed("the dot did not register with the tray watcher")
        conn = self._connection()
        path = "/" + self.item.split("/", 1)[1]
        props = self._call(
            conn,
            path,
            "org.freedesktop.DBus.Properties",
            "GetAll",
            ("org.kde.StatusNotifierItem",),
            "(s)",
        ).unpack()[0]
        if props.get("Id") != "io.github.trensoft.hotrec" or props.get("Status") != "Active":
            raise Failed(f"the dot is {props.get('Id')!r}, status {props.get('Status')!r}")
        self.menu_path, rows = self._menu(conn)
        shown = [(label, enabled) for label, (_id, enabled) in rows.items()]
        if shown != MENU:
            raise Failed(f"the menu of the dot is\n  {shown}\nnot\n  {MENU}")
        self.rows = rows
        return (
            f"registered as {self.item}, icon {props.get('IconName')}; "
            f"menu of {len(shown)} rows with the keys in them"
        )

    def step_windows(self) -> str:
        conn = self._connection()
        for label in ("About", "Settings…"):
            self._click(conn, self.menu_path, self.rows[label][0])
            time.sleep(3)
            if self.program.poll() is not None:
                raise Failed(f"hotrec ended with status {self.program.returncode} after {label!r}")
        text = self._read(self.program_log)
        if "Traceback" in text:
            raise Failed("a traceback after opening the windows:\n" + text[-1500:])
        return "'About' and 'Settings...' clicked, the dot is still running, no traceback"

    def step_single(self) -> str:
        before = self.desktop().count("ITEM-REGISTERED")
        second = self.hotrec("autostart", timeout=30)
        if second.returncode != 0:
            raise Failed(
                f"a second hotrec autostart ended with status {second.returncode}: "
                f"{second.stderr[-300:]!r}"
            )
        after = self.desktop().count("ITEM-REGISTERED")
        if after != before:
            raise Failed(f"a second dot was registered ({before} -> {after})")
        return "a second `hotrec autostart` ended with 0 and made no second dot"

    def step_quit(self) -> str:
        conn = self._connection()
        self._click(conn, self.menu_path, self.rows["Quit"][0])
        try:
            code = self.program.wait(timeout=30)
        except subprocess.TimeoutExpired:
            raise Failed("hotrec did not end 30 s after Quit") from None
        if code != 0:
            raise Failed(f"hotrec ended with status {code} after Quit, not 0")
        text = self._read(self.program_log)
        if "Traceback" in text:
            raise Failed("a traceback in the log of the program:\n" + text[-1500:])
        return "Quit ended hotrec autostart with status 0, no traceback in its log"

    def stop(self) -> None:
        for child in reversed(self.children):
            if child.poll() is None:
                child.terminate()
        for child in self.children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()

    def print_logs(self) -> None:
        for title, path in (
            ("gnome-shell", self.shell_log),
            ("hotrec autostart", self.program_log),
            ("fake desktop", self.desktop_log),
            ("fake logind", os.path.join(self.tmp, "login1.log")),
        ):
            lines = self._read(path).splitlines()[-40:]
            print(f"--- last lines of the log of {title}")
            print("\n".join(line[:300] for line in lines))


STEPS = ("shell", "loaded", "autostart", "extension", "dot", "windows", "single", "quit")
# A step that needs the result of another does not run when that one failed (and says so, FAIL: it
# is not a pass). The others do run: a Shell that finds the extension out of date still has a dot.
NEEDS = {
    "loaded": ("shell",),
    "autostart": ("shell",),
    "extension": ("autostart",),
    "dot": ("autostart",),
    "windows": ("dot",),
    "single": ("dot",),
    "quit": ("dot",),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--timeout", type=float, default=60, help="seconds to wait for each thing")
    args = parser.parse_args()
    failed: list[str] = []
    with tempfile.TemporaryDirectory(prefix="hotrec-gate-") as tmp:
        session = Session(tmp, args.timeout)
        try:
            for name in STEPS:
                broken = [need for need in NEEDS.get(name, ()) if need in failed]
                if broken:
                    failed.append(name)
                    print(
                        f"START-GATE {name} FAIL not run: the step {broken[0]} failed", flush=True
                    )
                    continue
                try:
                    print(
                        f"START-GATE {name} PASS {getattr(session, 'step_' + name)()}", flush=True
                    )
                except Exception as exc:  # every kind of failure is a failed step
                    failed.append(name)
                    print(f"START-GATE {name} FAIL {type(exc).__name__}: {exc}", flush=True)
        finally:
            if failed:
                session.print_logs()
            session.stop()
    return 1 if failed else 0


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    sys.exit(main())
