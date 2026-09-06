# SPDX-FileCopyrightText: Benjamin Davis
# SPDX-License-Identifier: MIT

from pathlib import Path

import pytest

import pyslang


@pytest.mark.parametrize(
    "stub_directory",
    [
        pytest.param(
            Path(pyslang.__file__).resolve().parent,
            id="public-package",
        ),
        pytest.param(
            Path(pyslang.__file__).resolve().parent / "pyslang",
            id="extension-package",
        ),
    ],
)
def test_submodule_stub_files_exist(
    stub_directory: Path, submodules: tuple[str, ...]
):
    """Each exposed sub-module should ship a companion ``.pyi`` stub file."""
    present = sorted(path.name for path in stub_directory.glob("*.pyi"))
    missing = [
        module for module in submodules if not (stub_directory / f"{module}.pyi").exists()
    ]
    assert not missing, (
        f"No type stub (.pyi) files for sub-modules {missing}.\n"
        f"Stub files actually shipped in {stub_directory}: {present}"
    )
