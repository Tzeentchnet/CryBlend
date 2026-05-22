"""Tests for `scripts/build_extension.py`.

These tests assert the layout Blender's extension installer requires:

- `blender_manifest.toml` at archive root.
- An `__init__.py` next to the manifest (required for `type = "add-on"`).
- No `__pycache__/` or `*.pyc` artefacts.
- The version embedded in the output filename matches the manifest.
"""

from __future__ import annotations

import importlib.util
import sys
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "build_extension.py"


def _load_build_module():
    spec = importlib.util.spec_from_file_location(
        "build_extension_under_test", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def built_zip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    build_mod = _load_build_module()
    out_dir = tmp_path_factory.mktemp("dist")
    version = build_mod.read_version()
    out_zip = out_dir / f"cryengine_importer-{version}.zip"
    build_mod.build(out_zip)
    return out_zip


def test_zip_exists_and_nonempty(built_zip: Path) -> None:
    assert built_zip.is_file()
    assert built_zip.stat().st_size > 0


def test_zip_root_contains_manifest(built_zip: Path) -> None:
    with zipfile.ZipFile(built_zip) as zf:
        names = zf.namelist()
    assert "blender_manifest.toml" in names


def test_addon_init_present(built_zip: Path) -> None:
    with zipfile.ZipFile(built_zip) as zf:
        assert "__init__.py" in zf.namelist()


def test_no_cache_or_pyc_artefacts(built_zip: Path) -> None:
    with zipfile.ZipFile(built_zip) as zf:
        for name in zf.namelist():
            assert "__pycache__" not in name, name
            assert not name.endswith((".pyc", ".pyo")), name


def test_zip_filename_matches_manifest_version(built_zip: Path) -> None:
    build_mod = _load_build_module()
    version = build_mod.read_version()
    assert built_zip.name == f"cryengine_importer-{version}.zip"
