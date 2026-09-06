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

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

import pyslang

# Sub-modules that the package publicly exposes (see pyslang/pyslang/__init__.py).
SUBMODULES = ["ast", "syntax", "parsing", "analysis", "driver"]

# A representative member of each sub-module used to probe the stubs.
SUBMODULE_PROBE_MEMBERS = {
    "ast": "Compilation",
    "syntax": "SyntaxTree",
    "parsing": "LexerOptions",
    "analysis": "AnalysisManager",
    "driver": "Driver",
}


@pytest.fixture(scope="module")
def example_py(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Write one probe containing all of the imports we want to check."""
    lines = [
        "import pyslang",
        "",
        "",
        "def top_level_import() -> None:",
    ]
    lines.extend(
        f"    reveal_type(pyslang.{module}.{member})"
        for module, member in SUBMODULE_PROBE_MEMBERS.items()
    )
    lines.extend(["", ""])

    lines.extend(["def import_from() -> None:"])
    lines.extend(f"    from pyslang import {module}" for module in SUBMODULES)
    lines.extend(
        f"    reveal_type({module}.{member})"
        for module, member in SUBMODULE_PROBE_MEMBERS.items()
    )

    path = tmp_path_factory.mktemp("stub-check") / "example.py"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _checker_command(name: str) -> list[str]:
    """Use a checker installed in the test interpreter when possible."""
    if importlib.util.find_spec(name) is not None:
        return [sys.executable, "-m", name]

    executable = shutil.which(name)
    if executable is None:
        pytest.skip(f"{name} is not installed")
    return [executable]


@pytest.fixture(scope="module")
def pyright_output(example_py: Path) -> dict[str, Any]:
    """Run pyright once and return its JSON output."""
    result = subprocess.run(
        [
            *_checker_command("pyright"),
            "--outputjson",
            "--pythonpath",
            sys.executable,
            str(example_py),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if not result.stdout.strip():
        pytest.fail(
            "pyright did not produce JSON output "
            f"(exit status {result.returncode}): {result.stderr}"
        )

    try:
        output = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        pytest.fail(f"Could not parse pyright output as JSON: {error}\n{result.stdout}")
    return output


@pytest.fixture(scope="module")
def mypy_output(example_py: Path) -> list[dict[str, Any]]:
    """Run mypy once and return its line-delimited JSON diagnostics."""
    result = subprocess.run(
        [
            *_checker_command("mypy"),
            "--no-incremental",
            "--no-error-summary",
            "--output=json",
            "--python-executable",
            sys.executable,
            str(example_py),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if not result.stdout.strip():
        pytest.fail(
            "mypy did not produce JSON output "
            f"(exit status {result.returncode}): {result.stderr}"
        )

    try:
        output = [
            json.loads(line) for line in result.stdout.splitlines() if line.strip()
        ]
    except json.JSONDecodeError as error:
        pytest.fail(f"Could not parse mypy output as JSON: {error}\n{result.stdout}")
    return output


def _format_diagnostics(diagnostics: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"  {diagnostic.get('file', '<unknown>')}:{diagnostic.get('line', '?')}: "
        f"{diagnostic.get('message', '<no message>')}"
        for diagnostic in diagnostics
    )


def test_submodule_stub_files_exist():
    """Each exposed sub-module should ship a companion ``.pyi`` stub file.

    The current build only produces a single ``pyslang.pyi`` (via
    ``nanobind_add_stub``), so the sub-module stubs are missing.
    """
    pkg = Path(pyslang.__file__).resolve().parent
    present = sorted(p.name for p in pkg.glob("*.pyi"))
    missing = [m for m in SUBMODULES if not (pkg / f"{m}.pyi").exists()]
    assert not missing, (
        f"No type stub (.pyi) files for sub-modules {missing}.\n"
        f"Stub files actually shipped in {pkg}: {present}"
    )


def test_submodule_members_are_typed(pyright_output: dict[str, Any]):
    """Pyright should resolve every probed member to a concrete type."""
    diagnostics = pyright_output.get("generalDiagnostics", [])
    errors = [
        diagnostic
        for diagnostic in diagnostics
        if diagnostic.get("severity") == "error"
    ]
    assert not errors, "pyright reported errors:\n" + _format_diagnostics(errors)

    reveals = [
        diagnostic
        for diagnostic in diagnostics
        if diagnostic.get("severity") == "information"
        and str(diagnostic.get("message", "")).startswith("Type of ")
    ]
    expected_reveals = len(SUBMODULE_PROBE_MEMBERS) * 2
    assert len(reveals) == expected_reveals, (
        f"Expected {expected_reveals} pyright reveal_type diagnostics, "
        f"got {len(reveals)}:\n{_format_diagnostics(reveals)}"
    )

    unknown = [
        diagnostic for diagnostic in reveals if "Unknown" in diagnostic["message"]
    ]
    assert not unknown, (
        "pyright could not resolve these members:\n" + _format_diagnostics(unknown)
    )


def test_submodule_members_are_typed_with_mypy(mypy_output: list[dict[str, Any]]):
    """Mypy should resolve every probed member to a concrete type."""
    errors = [
        diagnostic
        for diagnostic in mypy_output
        if diagnostic.get("severity") == "error"
    ]
    assert not errors, "mypy reported errors:\n" + _format_diagnostics(errors)

    reveals = [
        diagnostic
        for diagnostic in mypy_output
        if diagnostic.get("severity") == "note"
        and str(diagnostic.get("message", "")).startswith("Revealed type is ")
    ]
    expected_reveals = len(SUBMODULE_PROBE_MEMBERS) * 2
    assert len(reveals) == expected_reveals, (
        f"Expected {expected_reveals} mypy reveal_type diagnostics, "
        f"got {len(reveals)}:\n{_format_diagnostics(reveals)}"
    )

    unknown = [
        diagnostic for diagnostic in reveals if "Any" in diagnostic["message"]
    ]
    assert not unknown, (
        "mypy could not resolve these members:\n" + _format_diagnostics(unknown)
    )


# Check the flags definitions
@pytest.mark.parametrize(
    "flag_class", [
        pyslang.ast.ASTFlags,
    ],
)
def test_flags_none_members_exist(flag_class):
    assert hasattr(flag_class, "None_")
