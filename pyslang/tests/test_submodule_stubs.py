# SPDX-FileCopyrightText: Benjamin Davis
# SPDX-License-Identifier: MIT
"""Demonstrates a deficiency in the generated type stubs.

pyslang exposes its API through sub-modules (``pyslang.ast``, ``pyslang.syntax``,
``pyslang.parsing``, ``pyslang.analysis`` and ``pyslang.driver``). At runtime
these resolve fine, but the type stubs shipped in the wheel do **not** describe
them.

The wheel's stubs are produced by ``nanobind_add_stub`` in
``bindings/CMakeLists.txt``, which emits a *single* top-level ``pyslang.pyi``.
That stub even declares ``from pyslang import ast as ast, syntax as syntax, ...``
and refers to types such as ``ast.Symbol`` / ``parsing.LexerOptions`` -- but no
``ast.pyi`` / ``syntax.pyi`` / ... companion stubs are generated, so a type
checker resolves every sub-module member to ``Unknown``.

These tests encode the *desired* behaviour (sub-modules should be typed) and
therefore FAIL against the current build, demonstrating the gap. Nothing in the
build scripts or library source is modified.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pyslang = pytest.importorskip("pyslang")

# Sub-modules that the package publicly exposes (see pyslang/pyslang/__init__.py).
SUBMODULES = ["ast", "syntax", "parsing", "analysis", "driver"]

# A representative member of each sub-module used to probe the stubs.
PROBE_MEMBERS = {
    "ast": "Compilation",
    "syntax": "SyntaxTree",
    "parsing": "LexerOptions",
    "analysis": "AnalysisManager",
    "driver": "Driver",
}


def _package_dir() -> Path:
    return Path(pyslang.__file__).resolve().parent


def test_submodule_stub_files_exist():
    """Each exposed sub-module should ship a companion ``.pyi`` stub file.

    The current build only produces a single ``pyslang.pyi`` (via
    ``nanobind_add_stub``), so the sub-module stubs are missing.
    """
    pkg = _package_dir()
    present = sorted(p.name for p in pkg.glob("*.pyi"))
    missing = [m for m in SUBMODULES if not (pkg / f"{m}.pyi").exists()]
    assert not missing, (
        f"No type stub (.pyi) files for sub-modules {missing}.\n"
        f"Stub files actually shipped in {pkg}: {present}"
    )


@pytest.mark.skipif(shutil.which("pyright") is None, reason="pyright not installed")
def test_submodule_members_are_typed(tmp_path):
    """A type checker should resolve sub-module members to concrete types.

    Runs pyright over a probe that touches one member of each sub-module and
    asserts none of them come back as an unresolved attribute. Against the
    current stubs every access is reported as ``reportAttributeAccessIssue``.
    """
    lines = ["import pyslang"]
    lines += [f"from pyslang import {m}" for m in SUBMODULES]
    lines += [f"reveal_type({m}.{member})" for m, member in PROBE_MEMBERS.items()]
    probe = tmp_path / "probe.py"
    probe.write_text("\n".join(lines) + "\n")

    result = subprocess.run(
        [
            "pyright",
            "--outputjson",
            "--pythonpath",
            sys.executable,
            str(probe),
        ],
        capture_output=True,
        text=True,
    )
    # pyright exits non-zero when it finds errors; parse its JSON either way.
    data = json.loads(result.stdout)
    diagnostics = data.get("generalDiagnostics", [])
    attr_errors = [
        d
        for d in diagnostics
        if d.get("rule") in {"reportAttributeAccessIssue", "reportPrivateImportUsage"}
    ]

    detail = "\n".join(
        f"  line {d['range']['start']['line'] + 1}: {d['message'].splitlines()[0]}"
        for d in attr_errors
    )
    assert not attr_errors, (
        "Type checker could not resolve pyslang sub-module members; the shipped "
        "stubs do not type the ast/syntax/parsing/analysis/driver sub-modules:\n"
        + detail
    )
