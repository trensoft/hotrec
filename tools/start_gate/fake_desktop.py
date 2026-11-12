# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

"""The two desktop services Hotrec talks to, as stand-ins on a private (test) D-Bus session bus.

Hotrec tells the user things with ``notify-send`` (org.freedesktop.Notifications) and shows its top
bar dot as a StatusNotifierItem that a watcher (org.kde.StatusNotifierWatcher, the AppIndicator
extension of GNOME Shell) has to take. A container has neither, so this stands in for both and
writes what it was told into a log, one line each:

    NOTIFY <app> | <summary> | <body>
    ITEM-REGISTERED <service>

usage: fake_desktop.py LOGFILE
(the bus is DBUS_SESSION_BUS_ADDRESS; it prints "fake-desktop up" when it owns both names)
"""

import os
import sys

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

XML = """<node>
 <interface name="org.freedesktop.Notifications">
  <method name="Notify">
   <arg type="s" direction="in"/><arg type="u" direction="in"/><arg type="s" direction="in"/>
   <arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="as" direction="in"/>
   <arg type="a{sv}" direction="in"/><arg type="i" direction="in"/><arg type="u" direction="out"/>
  </method>
  <method name="GetCapabilities"><arg type="as" direction="out"/></method>
  <method name="GetServerInformation">
   <arg type="s" direction="out"/><arg type="s" direction="out"/>
   <arg type="s" direction="out"/><arg type="s" direction="out"/>
  </method>
  <method name="CloseNotification"><arg type="u" direction="in"/></method>
 </interface>
 <interface name="org.kde.StatusNotifierWatcher">
  <method name="RegisterStatusNotifierItem"><arg type="s" direction="in"/></method>
  <method name="RegisterStatusNotifierHost"><arg type="s" direction="in"/></method>
  <property name="RegisteredStatusNotifierItems" type="as" access="read"/>
  <property name="IsStatusNotifierHostRegistered" type="b" access="read"/>
  <property name="ProtocolVersion" type="i" access="read"/>
  <signal name="StatusNotifierItemRegistered"><arg type="s"/></signal>
  <signal name="StatusNotifierHostRegistered"/>
 </interface>
</node>"""

ITEMS: list[str] = []
LOG = None
NEXT_ID = [0]


def log(line: str) -> None:
    LOG.write(line + "\n")
    LOG.flush()


def on_call(conn, sender, path, iface, method, params, invocation):
    if iface == "org.freedesktop.Notifications":
        if method == "Notify":
            app, _id, _icon, summary, body = params.unpack()[:5]
            NEXT_ID[0] += 1
            log("NOTIFY %s | %s | %s" % (app, summary, body.replace("\n", " / ")))
            invocation.return_value(GLib.Variant("(u)", (NEXT_ID[0],)))
        elif method == "GetCapabilities":
            invocation.return_value(GLib.Variant("(as)", (["body"],)))
        elif method == "GetServerInformation":
            invocation.return_value(GLib.Variant("(ssss)", ("fake-desktop", "gate", "1", "1.2")))
        else:
            invocation.return_value(None)
    elif method == "RegisterStatusNotifierItem":
        service = params.unpack()[0]
        if service.startswith("/"):
            service = sender + service
        ITEMS.append(service)
        log("ITEM-REGISTERED %s (from %s)" % (service, sender))
        conn.emit_signal(
            None, path, iface, "StatusNotifierItemRegistered", GLib.Variant("(s)", (service,))
        )
        invocation.return_value(None)
    elif method == "RegisterStatusNotifierHost":
        invocation.return_value(None)
    else:
        invocation.return_error_literal(
            Gio.dbus_error_quark(), Gio.DBusError.UNKNOWN_METHOD, method
        )


def on_get(_conn, _sender, _path, _iface, prop):
    if prop == "RegisteredStatusNotifierItems":
        return GLib.Variant("as", ITEMS)
    if prop == "IsStatusNotifierHostRegistered":
        return GLib.Variant("b", True)
    if prop == "ProtocolVersion":
        return GLib.Variant("i", 0)
    return None


def main() -> int:
    global LOG
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    address = os.environ.get("DBUS_SESSION_BUS_ADDRESS")
    if not address:
        print("fake-desktop: DBUS_SESSION_BUS_ADDRESS is not set", file=sys.stderr)
        return 2
    LOG = open(sys.argv[1], "a", encoding="utf-8")
    flags = (
        Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
        | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION
    )
    conn = Gio.DBusConnection.new_for_address_sync(address, flags, None, None)
    interfaces = {i.name: i for i in Gio.DBusNodeInfo.new_for_xml(XML).interfaces}
    conn.register_object(
        "/org/freedesktop/Notifications",
        interfaces["org.freedesktop.Notifications"],
        on_call,
        None,
        None,
    )
    conn.register_object(
        "/StatusNotifierWatcher",
        interfaces["org.kde.StatusNotifierWatcher"],
        on_call,
        on_get,
        None,
    )
    for name in ("org.freedesktop.Notifications", "org.kde.StatusNotifierWatcher"):
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
        if reply.unpack()[0] != 1:
            print(
                "fake-desktop: RequestName %s answered %s" % (name, reply.unpack()), file=sys.stderr
            )
            return 1
    print("fake-desktop up", flush=True)
    GLib.MainLoop().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
