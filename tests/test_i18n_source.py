# SPDX-FileCopyrightText: 2026 TrenSoft
# SPDX-License-Identifier: GPL-3.0-or-later

"""The rules for the source (tools/i18n_catalog.py is what tools/i18n.sh check runs, too)."""

import ast
import importlib.util
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("i18n_catalog", REPO / "tools" / "i18n_catalog.py")
catalog = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(catalog)


def test_every_call_is_one_plain_literal_inside_a_function():
    calls = catalog.gettext_calls(REPO / "hotrec")
    assert len(calls) >= 20
    bad = [c for c in calls if c.msgid is None or c.at_import]
    assert bad == []


def test_no_other_gettext_spelling_in_the_source():
    for path in sorted((REPO / "hotrec").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
                assert name not in ("gettext", "ngettext", "pgettext", "dgettext"), (
                    path,
                    node.lineno,
                )


def test_the_catalog_tool_flags_what_it_should(tmp_path):
    source = tmp_path / "s"
    source.mkdir()
    (source / "m.py").write_text(
        "def f(x):\n    return _('ok'), _(x), _('a' + 'b')\n_('at import')\n", encoding="utf-8"
    )
    calls = catalog.gettext_calls(source)
    assert sorted((c.msgid or "", c.at_import) for c in calls) == [
        ("", False),
        ("", False),
        ("at import", True),
        ("ok", False),
    ]


def test_the_word_cpu_is_nowhere_in_what_the_user_sees_or_reads():
    """The software encoder is gone: not in the settings, the menus, the shortcuts, the catalogs
    or the documentation (tests may name it, to prove it is refused)."""
    found = []
    roots = [REPO / "hotrec", REPO / "data", REPO / "po", REPO / "docs", REPO / "packaging"]
    # The spec of gpu-screen-recorder is another package: it says why that program has no software
    # encoder here, which is a fact about it, not text of Hotrec.
    other_package = REPO / "packaging" / "fedora" / "gpu-screen-recorder.spec"
    files = [REPO / "README.md"] + [
        p
        for root in roots
        for p in root.rglob("*")
        if p.is_file() and p.suffix != ".mo" and p != other_package
    ]
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"\bcpu\b|libx264|x264", text, re.IGNORECASE):
            found.append(str(path.relative_to(REPO)))
    assert found == []
