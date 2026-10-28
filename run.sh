#!/usr/bin/env bash
# Run Hotrec from a checkout: ./run.sh video-audio | video | audio | pause | stop | status | setup
# The catalogs are built from po/ into the user's cache (when gettext is installed; without it
# the interface is English), and found through HOTREC_LOCALEDIR. For the keyboard shortcuts of a
# checkout:  ./run.sh shortcuts install --command "$PWD/run.sh"
set -euo pipefail

src="${BASH_SOURCE[0]}"
case "$src" in
    */*) dir="${src%/*}" ;;
    *) dir="." ;;
esac
repo="$(cd -- "$dir" && pwd)"

# A relative XDG_CACHE_HOME is not a place anybody means.
case "${XDG_CACHE_HOME:-}" in
    /*) cache="$XDG_CACHE_HOME/hotrec" ;;
    *) cache="${HOME:?HOME is not set}/.cache/hotrec" ;;
esac

if command -v msgfmt >/dev/null 2>&1 && command -v sha256sum >/dev/null 2>&1; then
    # The directory is named after the content of the catalogs: a changed catalog is a new
    # directory, nothing is overwritten while a recording key is being pressed.
    key="$(cat -- "$repo"/po/LINGUAS "$repo"/po/*.po | sha256sum | cut -c1-16)"
    locale="$cache/locale-$key"
    if [ ! -d "$locale" ]; then
        mkdir -p -- "$cache"
        tmp="$(mktemp -d -- "$cache/build.XXXXXX")"
        if "$repo/tools/i18n.sh" build "$tmp" >/dev/null 2>&1; then
            mv -T -- "$tmp" "$locale" 2>/dev/null || rm -rf -- "$tmp" # a parallel run was first
        else
            rm -rf -- "$tmp"
            locale=""
            echo "run.sh: the catalogs did not build, the interface stays English" >&2
        fi
    fi
    [ -z "$locale" ] || export HOTREC_LOCALEDIR="$locale"
fi

export PYTHONPATH="$repo${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m hotrec "$@"
