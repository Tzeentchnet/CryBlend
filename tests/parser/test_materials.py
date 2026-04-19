"""Phase 2 — material XML parser + pack-FS loader tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from cryengine_importer.io.pack_fs import InMemoryFileSystem, RealFileSystem
from cryengine_importer.materials import (
    Material,
    MaterialFlags,
    load_material,
    load_material_libraries,
)


_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


# --------------------------------------------------------------- parser


def test_parse_simple_xml_material() -> None:
    fs = RealFileSystem(_FIXTURES)
    mat = load_material("SimpleMat.xml", fs)

    assert mat is not None
    assert mat.shader == "Shader"
    assert mat.string_gen_mask == "%GLOSS_MAP"
    assert mat.use_specular_map
    assert not mat.use_bump_map
    assert mat.opacity == pytest.approx(1.0)
    assert mat.flags == MaterialFlags.ShaderGenMask64Bit
    assert mat.diffuse == pytest.approx(
        (0.073827766, 0.073827766, 0.073827766), rel=1e-5
    )
    assert mat.specular == pytest.approx((3.2, 3.2, 3.2), rel=1e-5)

    # Single material is wrapped into its own sub_materials list.
    assert mat.sub_materials == [mat]

    # Texture lookup table.
    diffuse = mat.texture("diffuse")
    normals = mat.texture("normals")
    specular = mat.texture("specular")
    env = mat.texture("env")
    assert diffuse is not None and diffuse.file == "objects/diffuse.tif"
    assert normals is not None and normals.file == "objects/bumpmap.tif"
    assert specular is not None and specular.file == "objects/specular.tif"
    assert env is not None and env.file == "environmentprobe.tif"


def test_parse_library_material_with_submaterials() -> None:
    fs = RealFileSystem(_FIXTURES)
    mat = load_material("MultipleMats.xml", fs)

    assert mat is not None
    names = [m.name for m in mat.sub_materials]
    assert names == ["body", "decals", "variant", "window", "generic"]

    # ``decals`` should have an empty Textures element.
    decals = next(m for m in mat.sub_materials if m.name == "decals")
    assert decals.textures == []

    # ``window`` has gen-mask flags decoded.
    window = next(m for m in mat.sub_materials if m.name == "window")
    assert {"GLOSS_MAP", "SPECULARPOW_GLOSSALPHA", "TESSELLATION"} <= window.gen_mask_flags
    assert window.use_specular_map
    assert window.use_gloss_in_specular_map

    # ``body`` has a glow attribute and submaterial-level public params.
    body = next(m for m in mat.sub_materials if m.name == "body")
    assert body.glow_amount == pytest.approx(0.75)
    assert "FresnelPower" in body.public_params
    assert body.public_params["FresnelPower"] == "4"


def test_parse_pbxml_material() -> None:
    """The pbxml fixture should round-trip through `cry_xml` and parse."""
    fs = RealFileSystem(_FIXTURES)
    mat = load_material("pbxml.mtl", fs)

    assert mat is not None
    # Top-level wrapper has no Name; first child is "Check_Point_mat".
    assert mat.sub_materials, "expected sub_materials from <SubMaterials>"
    assert mat.sub_materials[0].name == "Check_Point_mat"


# --------------------------------------------------------------- loader


def test_load_material_returns_none_for_missing_file() -> None:
    fs = InMemoryFileSystem()
    assert load_material("nope.mtl", fs) is None


def test_load_material_appends_mtl_extension_when_missing() -> None:
    """``Material.load_material("foo")`` should retry as ``foo.mtl``."""
    xml = (
        b'<?xml version="1.0"?>'
        b'<Material Shader="Illum" Diffuse="1,0,0" Opacity="1"/>'
    )
    fs = InMemoryFileSystem({"foo.mtl": xml})

    mat = load_material("foo", fs)
    assert mat is not None
    assert mat.shader == "Illum"
    assert mat.diffuse == pytest.approx((1.0, 0.0, 0.0))


def test_load_material_libraries_keys_by_lowercased_stem() -> None:
    xml_a = b'<Material Shader="A" Opacity="1"/>'
    xml_b = b'<Material Shader="B" Opacity="1"/>'
    fs = InMemoryFileSystem(
        {
            "materials/Hero.mtl": xml_a,
            "materials/villain.mtl": xml_b,
        }
    )

    libs = load_material_libraries(
        ["materials/Hero.mtl", "materials/villain.mtl"], fs
    )
    assert set(libs.keys()) == {"hero", "villain"}
    assert libs["hero"].shader == "A"
    assert libs["villain"].shader == "B"


def test_load_material_libraries_falls_back_to_object_dir() -> None:
    xml = b'<Material Shader="X" Opacity="1"/>'
    fs = InMemoryFileSystem({"objects/sub/hero.mtl": xml})

    # Raw name ``sub/hero.mtl`` doesn't exist, but joining with object_dir does.
    libs = load_material_libraries(["sub/hero.mtl"], fs, object_dir="objects")
    assert "hero" in libs
    assert libs["hero"].shader == "X"


# --------------------------------------------------------------- gen mask


def test_material_two_sided_flag() -> None:
    xml = b'<Material MtlFlags="2" Opacity="1"/>'
    fs = InMemoryFileSystem({"x.mtl": xml})
    mat = load_material("x.mtl", fs)
    assert mat is not None
    assert mat.is_two_sided
    assert MaterialFlags.TwoSided in mat.flags
