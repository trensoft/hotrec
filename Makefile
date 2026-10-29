# Installs the data files of Hotrec (everything except the Python package and the `hotrec` command,
# which pyproject.toml installs: `pip install .`, or %pyproject_install in a spec).
#
#   make install-data DESTDIR=/path/to/buildroot PREFIX=/usr [SYSCONFDIR=/etc]
#
# Needs gettext (msgfmt) for the translated launcher, metadata and catalogs.
PREFIX ?= /usr
DESTDIR ?=
SYSCONFDIR ?= /etc
APP_ID := io.github.trensoft.hotrec
DATADIR := $(DESTDIR)$(PREFIX)/share
ICONS := $(DATADIR)/icons/hicolor

.PHONY: install-data test lint
install-data:
	tmp=$$(mktemp -d) && trap 'rm -rf "$$tmp"' EXIT && \
	  tools/i18n.sh data "$$tmp" && \
	  install -Dpm 0644 "$$tmp/$(APP_ID).desktop" "$(DATADIR)/applications/$(APP_ID).desktop" && \
	  install -Dpm 0644 "$$tmp/$(APP_ID).metainfo.xml" "$(DATADIR)/metainfo/$(APP_ID).metainfo.xml" && \
	  tools/i18n.sh build "$$tmp/locale" && \
	  (cd "$$tmp/locale" && for lang in *; do \
	    install -Dpm 0644 "$$lang/LC_MESSAGES/$(APP_ID).mo" \
	      "$(DATADIR)/locale/$$lang/LC_MESSAGES/$(APP_ID).mo" || exit 1; done)
	install -Dpm 0644 data/icons/hicolor/scalable/apps/$(APP_ID).svg $(ICONS)/scalable/apps/$(APP_ID).svg
	install -Dpm 0644 data/icons/hicolor/scalable/status/$(APP_ID)-recording.svg \
	  $(ICONS)/scalable/status/$(APP_ID)-recording.svg
	install -Dpm 0644 data/icons/hicolor/scalable/status/$(APP_ID)-recording-off.svg \
	  $(ICONS)/scalable/status/$(APP_ID)-recording-off.svg
	install -Dpm 0644 data/icons/hicolor/scalable/status/$(APP_ID)-paused.svg \
	  $(ICONS)/scalable/status/$(APP_ID)-paused.svg
	install -Dpm 0644 data/icons/hicolor/symbolic/apps/$(APP_ID)-symbolic.svg \
	  $(ICONS)/symbolic/apps/$(APP_ID)-symbolic.svg
	install -Dpm 0644 packaging/man/hotrec.1 $(DATADIR)/man/man1/hotrec.1
	install -Dpm 0644 data/$(APP_ID)-autostart.desktop \
	  $(DESTDIR)$(SYSCONFDIR)/xdg/autostart/$(APP_ID)-autostart.desktop

test:
	python3 -m pytest

lint:
	ruff check .
	ruff format --check .
