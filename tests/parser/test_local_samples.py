"""End-to-end parser smoke tests against real on-disk sample assets.

These tests are intentionally **env-gated**: they only run when sample
folders are present on the local machine, so CI is unaffected.

Sample assets used:
- ARGO ATLS Power Suit (Star Citizen): a Cryengine character with skin
  meshes, a CDF, a CHR, and animated CGA prop pieces.
- Crysis "sewers" pack: a folder of static .cgf props.
- Crysis 3 squirrel: a small CryEngine 3 character with `.chrparams`
    CAF animation entries.

Override the default paths with env vars if your assets live elsewhere::

    set CRY_ATLS_DIR=D:\\my\\path\\ARGO\\ATLS
    set CRY_SEWERS_DIR=D:\\my\\path\\sewers
        set CRY3_OBJECTS_DIR=D:\\my\\path\\Cry3Objects
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from cryengine_importer.core import CryEngine
from cryengine_importer.io.pack_fs import CascadedPackFileSystem, RealFileSystem


# --------------------------------------------------------------- paths

_ATLS_DEFAULT = Path(r"C:\Users\kennpet\Downloads\PowerSuit\PowerSuit\ARGO\ATLS")
_SEWERS_DEFAULT = Path(r"C:\Users\kennpet\Downloads\sewers")
_CRY3_OBJECTS_DEFAULT = Path(r"E:\SafeToCopy\Models\Cry3Objects")

ATLS_DIR = Path(os.environ.get("CRY_ATLS_DIR", str(_ATLS_DEFAULT)))
SEWERS_DIR = Path(os.environ.get("CRY_SEWERS_DIR", str(_SEWERS_DEFAULT)))
CRY3_OBJECTS_DIR = Path(
    os.environ.get("CRY3_OBJECTS_DIR", str(_CRY3_OBJECTS_DEFAULT))
)


def _require_dir(path: Path) -> None:
    if not path.is_dir():
        pytest.skip(f"sample dir not present: {path}")


def _load(asset_dir: Path, file_name: str) -> CryEngine:
    """Run the parser end-to-end on one file inside ``asset_dir``."""
    _require_dir(asset_dir)
    asset_path = asset_dir / file_name
    if not asset_path.is_file():
        pytest.skip(f"asset not present: {asset_path}")
    fs = RealFileSystem(str(asset_dir))
    eng = CryEngine(file_name, fs, object_dir=str(asset_dir))
    eng.process()
    return eng


def _load_with_animation_layer(
    asset_dir: Path,
    file_name: str,
    animations_dir: Path,
) -> CryEngine:
    """Run the parser with a second root for extracted CAF files."""
    _require_dir(asset_dir)
    _require_dir(animations_dir)
    asset_path = asset_dir / Path(file_name)
    if not asset_path.is_file():
        pytest.skip(f"asset not present: {asset_path}")
    fs = CascadedPackFileSystem(
        [RealFileSystem(str(asset_dir)), RealFileSystem(str(animations_dir))]
    )
    eng = CryEngine(file_name.replace("\\", "/"), fs, object_dir=str(asset_dir))
    eng.process()
    return eng


# --------------------------------------------------------------- ATLS


@pytest.mark.parametrize(
    "skin_name",
    [
        "argo_atls_powersuit_l_arm.skin",
        "argo_atls_powersuit_r_arm.skin",
        "argo_atls_powersuit_l_leg.skin",
        "argo_atls_powersuit_r_leg.skin",
        "argo_atls_powersuit_trunk.skin",
    ],
)
def test_atls_skin_pieces_parse(skin_name: str) -> None:
    eng = _load(ATLS_DIR, skin_name)
    assert eng.models, f"{skin_name}: no models loaded"
    # Skin assets are Ivo-format in modern SC builds.
    assert eng.is_ivo, f"{skin_name}: expected Ivo signature"


def test_atls_chr_parses_and_loads_chrparams() -> None:
    eng = _load(ATLS_DIR, "argo_atls_powersuit.chr")
    assert eng.models
    # Sibling .chrparams should be auto-discovered.
    assert eng.chrparams is not None, "expected chrparams to load alongside .chr"


def test_atls_chr_skinning_has_bones() -> None:
    eng = _load(ATLS_DIR, "argo_atls_powersuit.chr")
    assert eng.skinning_info.compiled_bones, "expected skeleton bones from .chr"


def test_atls_ui_screen_cga_has_geometry() -> None:
    eng = _load(ATLS_DIR, "argo_atls_powersuit_ui_screen.cga")
    assert eng.models
    # The .cga + .cgam pair should both load.
    assert len(eng.models) >= 2, "expected .cga and companion .cgam"
    assert any(n.mesh_data is not None for n in eng.nodes), \
        "expected at least one mesh node in the UI screen prop"


# ------------------------------------------------------------- Sewers


@pytest.mark.parametrize(
    "cgf_name",
    [
        "bridge_across.cgf",
        "sewer_across.cgf",
        "hall.cgf",
        "pipe_straight.cgf",
        "pool_floor.cgf",
        "columns_sewer_across.cgf",
        "ramp.cgf",
    ],
)
def test_crysis_sewers_cgf_parses(cgf_name: str) -> None:
    eng = _load(SEWERS_DIR, cgf_name)
    assert eng.models, f"{cgf_name}: no models loaded"
    assert not eng.is_ivo, f"{cgf_name}: Crysis 1 assets should not be Ivo"
    assert eng.root_node is not None, f"{cgf_name}: no root node built"
    assert any(n.mesh_data is not None for n in eng.nodes), \
        f"{cgf_name}: expected at least one mesh node"


# ----------------------------------------------------------- Crysis 3 squirrel


def test_crysis3_squirrel_chr_loads_animation_clips() -> None:
    eng = _load_with_animation_layer(
        CRY3_OBJECTS_DIR,
        "Objects/characters/animals/squirrel/squirrel.chr",
        CRY3_OBJECTS_DIR / "Animations",
    )

    assert eng.chrparams is not None, "expected squirrel.chrparams to load"
    assert len(eng.animation_models) == 3
    assert {clip.name for clip in eng.animation_clips} == {
        "idle01",
        "walk_loop",
        "run_loop",
    }
    assert all(clip.rotation_track_count > 0 for clip in eng.animation_clips)
    assert any(clip.position_track_count > 0 for clip in eng.animation_clips)


def test_crysis3_squirrel_chr_finds_nested_animation_root() -> None:
    eng = _load(
        CRY3_OBJECTS_DIR,
        "Objects/characters/animals/squirrel/squirrel.chr",
    )

    assert eng.chrparams is not None, "expected squirrel.chrparams to load"
    assert {clip.name for clip in eng.animation_clips} == {
        "idle01",
        "walk_loop",
        "run_loop",
    }
