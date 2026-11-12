# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

"""The two stand-in desktop services of the start gate (``tools/start_gate/fake_desktop.py`` and
``fake_login1.py``), run on a real private D-Bus session bus.

They are what the gate's GNOME Shell session gets in place of the notification daemon, the tray
watcher and logind. The tests need PyGObject and ``dbus-daemon``: where they are not installed (the
CI of this repository does not have PyGObject) the tests are skipped, and the gate itself, which
runs them in the container, is what proves them.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from start_gate_helpers import GATE

gi = pytest.importorskip("gi", reason="PyGObject is not installed")
pytestmark = pytest.mark.skipif(shutil.which("dbus-daemon") is None, reason="no dbus-daemon")

BUS_CONFIG = """<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-Bus Bus Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig><type>session</type><listen>unix:path={path}</listen><auth>EXTERNAL</auth>
<policy context="default"><allow send_destination="*" eavesdrop="true"/><allow eavesdrop="true"/>
<allow own="*"/></policy></busconfig>
"""


@pytest.fixture
def bus(tmp_path):
    path = tmp_path / "bus.sock"
    config = tmp_path / "bus.conf"
    config.write_text(BUS_CONFIG.format(path=path), encoding="utf-8")
    daemon = subprocess.Popen(["dbus-daemon", "--nofork", f"--config-file={config}"])
    for _ in range(100):
        if path.exists():
            break
        time.sleep(0.05)
    else:
        daemon.kill()
        pytest.fail("the test bus did not come up")
    yield f"unix:path={path}"
    daemon.terminate()
    daemon.wait(timeout=10)


def _start(script, bus, tmp_path, *args, env_name="DBUS_SESSION_BUS_ADDRESS", ready="up"):
    env = {"PATH": "/usr/bin:/bin", env_name: bus}
    child = subprocess.Popen(
        [sys.executable, "-W", "ignore", str(GATE / script), *args],
        env=env,
        stdout=subprocess.PIPE,
        text=True,
    )
    line = child.stdout.readline()
    assert ready in line, line
    return child


def _connection(bus):
    gi.require_version("Gio", "2.0")
    from gi.repository import Gio

    flags = (
        Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
        | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION
    )
    return Gio.DBusConnection.new_for_address_sync(bus, flags, None, None)


def _call(conn, name, path, interface, method, args=None, signature=None):
    from gi.repository import Gio, GLib

    return conn.call_sync(
        name,
        path,
        interface,
        method,
        GLib.Variant(signature, args) if signature else None,
        None,
        Gio.DBusCallFlags.NONE,
        10000,
        None,
    )


@pytest.fixture
def desktop(bus, tmp_path):
    log = tmp_path / "desktop.log"
    child = _start("fake_desktop.py", bus, tmp_path, str(log), ready="fake-desktop up")
    yield log
    child.terminate()
    child.wait(timeout=10)


def test_the_desktop_logs_a_notification_with_its_application_summary_and_body(bus, desktop):
    conn = _connection(bus)
    reply = _call(
        conn,
        "org.freedesktop.Notifications",
        "/org/freedesktop/Notifications",
        "org.freedesktop.Notifications",
        "Notify",
        ("Hotrec", 0, "icon", "A summary", "line one\nline two", [], {}, -1),
        "(susssasa{sv}i)",
    )
    assert reply.unpack()[0] >= 1
    assert desktop.read_text(encoding="utf-8").splitlines() == [
        "NOTIFY Hotrec | A summary | line one / line two"
    ]


def test_the_desktop_ids_of_notifications_are_not_the_same(bus, desktop):
    conn = _connection(bus)
    args = ("a", 0, "", "s", "b", [], {}, -1)
    call = ("org.freedesktop.Notifications", "/org/freedesktop/Notifications")
    first = _call(conn, *call, "org.freedesktop.Notifications", "Notify", args, "(susssasa{sv}i)")
    second = _call(conn, *call, "org.freedesktop.Notifications", "Notify", args, "(susssasa{sv}i)")
    assert first.unpack()[0] != second.unpack()[0]


def test_the_desktop_has_the_tray_watcher_that_takes_an_item_and_logs_it(bus, desktop):
    conn = _connection(bus)
    watcher = ("org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher")
    interface = "org.kde.StatusNotifierWatcher"
    _call(conn, *watcher, interface, "RegisterStatusNotifierItem", ("/org/x/Item",), "(s)")
    _call(conn, *watcher, interface, "RegisterStatusNotifierItem", (":1.99/org/y/Item",), "(s)")
    lines = desktop.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("ITEM-REGISTERED :") and " /org/x/Item" not in lines[0]
    assert "/org/x/Item (from :" in lines[0]
    assert lines[1].startswith("ITEM-REGISTERED :1.99/org/y/Item (from :")
    items = _call(
        conn,
        *watcher,
        "org.freedesktop.DBus.Properties",
        "Get",
        (interface, "RegisteredStatusNotifierItems"),
        "(ss)",
    ).unpack()[0]
    assert len(items) == 2 and items[1] == ":1.99/org/y/Item"
    host = _call(
        conn,
        *watcher,
        "org.freedesktop.DBus.Properties",
        "Get",
        (interface, "IsStatusNotifierHostRegistered"),
        "(ss)",
    ).unpack()[0]
    assert host is True


def test_the_desktop_says_what_the_server_is(bus, desktop):
    conn = _connection(bus)
    info = _call(
        conn,
        "org.freedesktop.Notifications",
        "/org/freedesktop/Notifications",
        "org.freedesktop.Notifications",
        "GetServerInformation",
    ).unpack()
    assert info[0] == "fake-desktop" and len(info) == 4


def test_the_desktop_needs_a_log_file_and_a_bus(bus, tmp_path):
    no_log = subprocess.run(
        [sys.executable, str(GATE / "fake_desktop.py")],
        env={"PATH": "/usr/bin:/bin", "DBUS_SESSION_BUS_ADDRESS": bus},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert no_log.returncode == 2
    no_bus = subprocess.run(
        [sys.executable, str(GATE / "fake_desktop.py"), str(tmp_path / "log")],
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert no_bus.returncode == 2 and "DBUS_SESSION_BUS_ADDRESS is not set" in no_bus.stderr


@pytest.fixture
def logind(bus, tmp_path):
    child = _start(
        "fake_login1.py", bus, tmp_path, env_name="DBUS_SYSTEM_BUS_ADDRESS", ready="fake-login1 up"
    )
    yield bus
    child.terminate()
    child.wait(timeout=10)


def test_logind_gives_the_session_of_a_process_and_a_delay_lock(logind):
    conn = _connection(logind)
    name, path = "org.freedesktop.login1", "/org/freedesktop/login1"
    manager = "org.freedesktop.login1.Manager"
    session = _call(conn, name, path, manager, "GetSessionByPID", (1234,), "(u)")
    assert session.unpack()[0] == "/org/freedesktop/login1/session/1"
    _call(conn, name, session.unpack()[0], "org.freedesktop.login1.Session", "Lock")
    delay = _call(
        conn,
        name,
        path,
        "org.freedesktop.DBus.Properties",
        "Get",
        ("org.freedesktop.login1.Manager", "InhibitDelayMaxUSec"),
        "(ss)",
    )
    assert delay.unpack()[0] == 5_000_000
    locked = _call(
        conn,
        name,
        session.unpack()[0],
        "org.freedesktop.DBus.Properties",
        "Get",
        ("org.freedesktop.login1.Session", "LockedHint"),
        "(ss)",
    )
    assert locked.unpack()[0] is False


def test_logind_needs_the_system_bus_address():
    result = subprocess.run(
        [sys.executable, str(GATE / "fake_login1.py")],
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 2
    assert Path(GATE / "fake_login1.py").exists()


# ---- every method and property the fakes answer, and what they answer (survivors of the sweep) --

NOTIFICATIONS = ("org.freedesktop.Notifications", "/org/freedesktop/Notifications")
WATCHER = ("org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher")


def _property(conn, target, interface, name):
    return _call(
        conn,
        *target,
        "org.freedesktop.DBus.Properties",
        "Get",
        (interface, name),
        "(ss)",
    ).unpack()[0]


def test_the_desktop_has_the_capabilities_of_a_server_that_shows_a_body(bus, desktop):
    conn = _connection(bus)
    caps = _call(conn, *NOTIFICATIONS, "org.freedesktop.Notifications", "GetCapabilities")
    assert caps.unpack() == (["body"],)


def test_the_desktop_names_itself_in_full_and_closes_a_notification_with_no_answer(bus, desktop):
    conn = _connection(bus)
    info = _call(conn, *NOTIFICATIONS, "org.freedesktop.Notifications", "GetServerInformation")
    assert info.unpack() == ("fake-desktop", "gate", "1", "1.2")
    closed = _call(
        conn, *NOTIFICATIONS, "org.freedesktop.Notifications", "CloseNotification", (7,), "(u)"
    )
    assert closed.unpack() == ()
    assert desktop.read_text(encoding="utf-8") == ""


def test_the_desktop_takes_a_tray_host_and_registers_no_item_for_it(bus, desktop):
    conn = _connection(bus)
    answer = _call(
        conn, *WATCHER, "org.kde.StatusNotifierWatcher", "RegisterStatusNotifierHost", ("h",), "(s)"
    )
    assert answer.unpack() == ()
    assert desktop.read_text(encoding="utf-8") == ""
    interface = "org.kde.StatusNotifierWatcher"
    assert _property(conn, WATCHER, interface, "RegisteredStatusNotifierItems") == []


def test_the_watcher_has_a_host_and_speaks_protocol_0_and_lists_its_items(bus, desktop):
    conn = _connection(bus)
    interface = "org.kde.StatusNotifierWatcher"
    assert _property(conn, WATCHER, interface, "IsStatusNotifierHostRegistered") is True
    version = _call(
        conn,
        *WATCHER,
        "org.freedesktop.DBus.Properties",
        "Get",
        (interface, "ProtocolVersion"),
        "(ss)",
    )
    assert version.get_type_string() == "(v)"
    assert version.get_child_value(0).get_variant().get_type_string() == "i"
    assert version.unpack()[0] == 0


def _owner(bus, name):
    """A connection that owns ``name``, so that a fake that comes after it cannot."""
    from gi.repository import Gio, GLib

    conn = _connection(bus)
    reply = conn.call_sync(
        "org.freedesktop.DBus",
        "/org/freedesktop/DBus",
        "org.freedesktop.DBus",
        "RequestName",
        GLib.Variant("(su)", (name, 0)),
        None,
        Gio.DBusCallFlags.NONE,
        -1,
        None,
    )
    assert reply.unpack()[0] == 1
    return conn


@pytest.mark.parametrize(
    "script, env_name, name, args, message",
    [
        (
            "fake_desktop.py",
            "DBUS_SESSION_BUS_ADDRESS",
            "org.kde.StatusNotifierWatcher",
            ("LOG",),
            "RequestName org.kde.StatusNotifierWatcher answered",
        ),
        (
            "fake_login1.py",
            "DBUS_SYSTEM_BUS_ADDRESS",
            "org.freedesktop.login1",
            (),
            "fake-login1: RequestName answered",
        ),
    ],
)
def test_a_fake_that_cannot_own_its_name_says_so_and_ends_with_1(
    bus, tmp_path, script, env_name, name, args, message
):
    """Not the primary owner of the name: the Shell would talk to something else. No "up" line."""
    owner = _owner(bus, name)
    args = [str(tmp_path / "log") if arg == "LOG" else arg for arg in args]
    result = subprocess.run(
        [sys.executable, "-W", "ignore", str(GATE / script), *args],
        env={"PATH": "/usr/bin:/bin", env_name: bus},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    owner.close_sync(None)
    assert result.returncode == 1, (result.stdout, result.stderr)
    assert message in result.stderr
    assert "up" not in result.stdout


def test_logind_hands_out_a_delay_lock_as_a_file_descriptor(logind):
    from gi.repository import Gio, GLib

    conn = _connection(logind)
    reply, fds = conn.call_with_unix_fd_list_sync(
        "org.freedesktop.login1",
        "/org/freedesktop/login1",
        "org.freedesktop.login1.Manager",
        "Inhibit",
        GLib.Variant("(ssss)", ("sleep", "who", "why", "delay")),
        GLib.VariantType("(h)"),
        Gio.DBusCallFlags.NONE,
        10000,
        None,
        None,
    )
    assert reply.unpack() == (0,)
    assert fds.get_length() == 1
