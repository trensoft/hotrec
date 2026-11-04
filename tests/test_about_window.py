# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

"""The About window with a stand-in for GTK 3 (how it looks is a check on a real desktop)."""

from types import SimpleNamespace

from hotrec import APP_ID, ISSUES_URL, LICENSE, WEBSITE, __version__, about_window


class Widget:
    def __init__(self, kind, **kwargs):
        self.kind = kind
        self.label = kwargs.get("label", "")
        self.title = kwargs.get("title")
        self.uri = kwargs.get("uri")
        self.handlers = {}
        self.destroyed = False
        self.presented = 0

    def __getattr__(self, name):
        if name.startswith(("set_", "add", "get_", "pack_", "show_")):
            return lambda *args, **kwargs: self
        raise AttributeError(name)

    def connect(self, name, handler, *data):
        self.handlers[name] = (handler, data)

    def present(self):
        self.presented += 1

    def destroy(self):
        self.destroyed = True
        self.handlers["destroy"][0](self)


class FakeGtk:
    Orientation = SimpleNamespace(VERTICAL=1)
    IconSize = SimpleNamespace(DIALOG=6)
    Justification = SimpleNamespace(CENTER=2)

    def __init__(self):
        self.made = []
        for name in ("Window", "Box", "Label", "Button"):
            setattr(self, name, self._maker(name))
        gtk = self
        self.LinkButton = SimpleNamespace(new_with_label=lambda uri, label: gtk._link(uri, label))
        self.Image = SimpleNamespace(
            new_from_icon_name=lambda icon, size: gtk._made("Image", label=icon)
        )

    def _made(self, kind, **kwargs):
        widget = Widget(kind, **kwargs)
        self.made.append(widget)
        return widget

    def _maker(self, kind):
        return lambda **kwargs: self._made(kind, **kwargs)

    def _link(self, uri, label):
        return self._made("LinkButton", uri=uri, label=label)

    def of(self, kind):
        return [w for w in self.made if w.kind == kind]


def test_the_about_window_has_name_version_description_links_license_and_close():
    gtk = FakeGtk()
    window = about_window.open_about(gtk, APP_ID)
    assert gtk.of("Window")[0].title == "About"
    assert [w.label for w in gtk.of("Label")] == [
        "Hotrec",
        "Version %s" % __version__,
        "Screen and sound recorder for GNOME, driven by keyboard shortcuts.",
        "License: %s" % LICENSE,
    ]
    assert [(w.label, w.uri) for w in gtk.of("LinkButton")] == [
        ("Website", WEBSITE),
        ("Report a problem", ISSUES_URL),
    ]
    assert [w.label for w in gtk.of("Button")] == ["Close"]
    assert gtk.of("Image")[0].label == APP_ID
    assert window.closed is False


def test_the_addresses_and_the_license_are_the_ones_of_the_project():
    assert WEBSITE == "https://github.com/trensoft/hotrec"
    assert ISSUES_URL == WEBSITE + "/issues"
    assert LICENSE == "GPL-3.0-or-later"
    assert __version__ == "0.1.6"


def test_close_closes_and_present_brings_the_window_forward():
    gtk = FakeGtk()
    window = about_window.open_about(gtk)
    window.present()
    assert gtk.of("Window")[0].presented == 1
    gtk.of("Button")[0].handlers["clicked"][0](None)
    assert gtk.of("Window")[0].destroyed and window.closed is True


def test_without_an_icon_name_there_is_no_picture():
    gtk = FakeGtk()
    about_window.open_about(gtk, None)
    assert gtk.of("Image") == []
