# Source-RPM builder for COPR ("Make srpm" source type). COPR runs, inside the checkout,
#   make -f .copr/Makefile srpm outdir=<dir> spec=<spec file>
# and takes the *.src.rpm it finds in <dir>.
#
# Two kinds of spec are built with this one file (the trensoft/hotrec COPR project has two packages):
#   - a spec whose Source0 is a plain file name (hotrec.spec): the tarball is made from the checkout itself
#     (git archive of HEAD), named as Source0 names it, so nothing is downloaded;
#   - a spec whose Source0 is an https URL (gpu-screen-recorder.spec): the file is downloaded once into
#     DIR/sources and checked against packaging/fedora/<Name>.sha256 (next to the spec); no checksum file,
#     or a mismatch, stops the build. That is the only network use; no secret is needed. It needs git, gzip, rpmbuild, sed, grep and head;
# the "tools" target checks for them before anything else runs (see there).
#
# A relative spec is taken from the root of the checkout, not from the directory make was started in.
# The tarball is of the HEAD commit: what is changed but not committed is not in it. A path with a
# space or a quote, and a Name or Version that is not [A-Za-z0-9._+-]+, stop the build with an error.
#
#   make -f .copr/Makefile tools                only the check of the commands the recipes use
#   make -f .copr/Makefile tarball outdir=DIR   only the tarball: DIR/sources/<name>-<version>.tar.gz
#   make -f .copr/Makefile srpm outdir=DIR      the tarball, then DIR/<name>-<version>-<release>.src.rpm

ifneq ($(words $(MAKEFILE_LIST)),1)
$(error this file must be the only makefile loaded, and its path must not hold a space: '$(MAKEFILE_LIST)')
endif
root    := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/..)
spec    ?= packaging/fedora/hotrec.spec
specfile = $(if $(filter /%,$(spec)),$(spec),$(root)/$(spec))
outdir  ?= .
out      = $(abspath $(outdir))

# The recipes put the paths in single quotes, which a space or a quote in them would break (the
# $(abspath) above also splits at a space), so they are refused instead of written to the wrong place.
space   := $(subst ,, )
$(foreach v,root spec outdir out specfile,$(if $(or $(word 2,$($v)),$(findstring $(space),$($v)),$(findstring ',$($v))),$(error $v must not hold a space or a quote: '$($v)')))

# The first Name: and Version: line, and only a value of the allowed characters (grep prints nothing
# for any other, so $(name) or $(version) is empty and the tarball target stops).
field    = $(shell sed -n '/^$1:/{s/^$1:[[:space:]]*//;s/[[:space:]]*$$//;p;}' '$(specfile)' | head -n 1 | grep -E '^[A-Za-z0-9._+-]+$$')
name     = $(call field,Name)
version  = $(call field,Version)

# Source0 (or Source) with %{name} and %{version} filled in; remote when it holds a URL.
source0  = $(subst %{version},$(version),$(subst %{name},$(name),$(shell sed -n '/^Source0\{0,1\}:/{s/^Source0\{0,1\}:[[:space:]]*//;s/[[:space:]]*$$//;p;}' '$(specfile)' | head -n 1)))
remote   = $(findstring ://,$(source0))
shafile  = $(dir $(specfile))$(name).sha256

# The commands the recipes run. COPR starts the source build in a bare chroot, so they may be missing.
# All present: nothing is done and nothing is run. Some missing and this is root with dnf: the
# packages below are installed with dnf, then all are checked again. Otherwise (not root, no dnf, or
# still missing after the install) it stops with the list. No sudo; the network is used by dnf and, for a URL Source0, by curl.
# sed, grep, head and sha256sum belong to the base system and are only checked, not installed.
tools   := git gzip rpmbuild sed grep head curl sha256sum
pkgs    := git-core rpm-build gzip curl coreutils

.PHONY: tools tarball srpm

tools:
	@miss() { m=; for t in $(tools); do command -v "$$t" >/dev/null 2>&1 || m="$$m $$t"; done; echo $$m; }; \
	missing=$$(miss); \
	test -n "$$missing" || exit 0; \
	if test "$$(id -u)" = 0 && command -v dnf >/dev/null 2>&1; then \
	    echo "missing: $$missing; installing: dnf -y install $(pkgs)" >&2; \
	    dnf -y install $(pkgs) || exit 1; \
	    missing=$$(miss); \
	    test -z "$$missing" || { echo "still missing after the install: $$missing" >&2; exit 1; }; \
	else \
	    echo "missing: $$missing; install: dnf install $(pkgs) (as root; this file does not use sudo)" >&2; \
	    exit 1; \
	fi

tarball: tools
	@test -n '$(name)' && test -n '$(version)' || { echo 'no usable Name or Version ([A-Za-z0-9._+-]+) in $(specfile)' >&2; exit 1; }
	mkdir -p '$(out)/sources'
ifeq ($(remote),)
	git -c safe.directory='*' -c tar.tar.gz.command='gzip -cn' -C '$(root)' archive --format=tar.gz \
	    --prefix='$(name)-$(version)/' -o '$(out)/sources/$(name)-$(version).tar.gz' HEAD
else
	@case '$(source0)' in https://*[!A-Za-z0-9._+/:%-]*|https://) echo "unusable Source0 URL: $(source0)" >&2; exit 1;; https://*) ;; *) echo "Source0 must be an https URL: $(source0)" >&2; exit 1;; esac
	@test -f '$(shafile)' || { echo 'no checksum file $(shafile): a remote Source0 needs one' >&2; exit 1; }
	curl -fsSL --retry 3 -o '$(out)/sources/$(notdir $(source0))' '$(source0)'
	cd '$(out)/sources' && sha256sum -c '$(shafile)'
endif

srpm: tarball
	rpmbuild -bs '$(specfile)' --define '_sourcedir $(out)/sources' --define '_srcrpmdir $(out)'
