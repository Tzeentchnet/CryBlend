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
from cryengine_importer.materials.material import (
    Texture,
    classify_texture_suffix,
    extract_color_params,
    extract_scalar_params,
    extract_tint_colors,
    is_primary_tint_key,
    parse_color_value,
    parse_scalar_value,
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


# ------------------------------------------------ texture-suffix conventions


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("objects/atlas_body_diff.tif", "diffuse"),
        ("objects/atlas_body_DIFF.dds", "diffuse"),
        ("objects/atlas_body_ddna.tif", "normals_gloss"),
        ("objects/atlas_body_ddn.tif", "normals"),
        ("objects/atlas_body_spec.tif", "specular"),
        ("textures/floor_displ.tif", "height"),
        ("textures/floor_disp.tif", "height"),
        ("textures/wall_pom_height.tif", "height"),
        ("decals/scratch_decal.tif", "decal"),
        ("decals/scratch_damage.tif", "decal"),
        ("decals/scratch_stencil.tif", "decal"),
        ("fx/fire_em.tif", "emittance"),
        ("ground/grass_ao.tif", "occlusion"),
        # No recognised suffix → None (caller falls back to Map=).
        ("objects/bumpmap.tif", None),
        ("", None),
        # `_pom_height` must win over a naive `_height` check (we do
        # not actually have `_height` in the table, but verify priority
        # by checking the `_pom_height` -> height mapping).
        ("path/to/wall_pom_height.dds", "height"),
        # `_displ` (longer) must beat `_disp` when checked in order.
        ("path/to/wall_displ.dds", "height"),
    ],
)
def test_classify_texture_suffix(path: str, expected: str | None) -> None:
    assert classify_texture_suffix(path) == expected


def test_texture_slot_prefers_suffix_over_map_attribute() -> None:
    """A DDNA file with ``Map="Diffuse"`` should still be recognised as
    a packed normal-gloss map — Crytek artists frequently leave the
    Map attribute as Diffuse on packed textures."""
    tex = Texture(map="Diffuse", file="objects/atlas_body_ddna.tif")
    assert tex.slot == "normals_gloss"


def test_texture_slot_falls_back_to_map_attribute() -> None:
    tex = Texture(map="Bumpmap", file="objects/bumpmap.tif")
    assert tex.slot == "normals"


def test_texture_slot_unknown_map_lowercased() -> None:
    tex = Texture(map="MysteryMap", file="x.tif")
    assert tex.slot == "mysterymap"


# ------------------------------------------------------ tint palette helpers


def test_parse_color_value_three_floats() -> None:
    assert parse_color_value("0.04518621,0.04518621,0.5") == pytest.approx(
        (0.04518621, 0.04518621, 0.5)
    )


@pytest.mark.parametrize(
    "value",
    ["", "1,2", "1,2,3,4", "a,b,c", None],
)
def test_parse_color_value_rejects_non_triples(value: str | None) -> None:
    assert parse_color_value(value or "") is None


def test_parse_scalar_value_roundtrip() -> None:
    assert parse_scalar_value("0.55536944") == pytest.approx(0.55536944)
    assert parse_scalar_value("1") == pytest.approx(1.0)
    assert parse_scalar_value("") is None
    assert parse_scalar_value("not-a-number") is None


def test_extract_color_and_scalar_params_partition_public_params() -> None:
    """SC `Anodized_01_A` PublicParams (verbatim from `SC_mat.mtl`)."""
    pp = {
        "TilingScale1": "1",
        "DirtColor": "0.1301365,0.10461649,0.080219828",
        "DiffuseTint1": "0.04518621,0.04518621,0.04518621",
        "DiffuseTintWear1": "0.16826943,0.16826943,0.16826943",
        "PomSelfShadowStrength": "1",
        "PomDisplacement": "0.0049999999",
        "GlossMultWear1": "0.55536944",
        "GlossMult1": "0.80000001",
        "TilingScaleWear1": "1",
        "PomHeightBias": "1",
    }

    colors = extract_color_params(pp)
    scalars = extract_scalar_params(pp)

    assert set(colors) == {"DirtColor", "DiffuseTint1", "DiffuseTintWear1"}
    assert colors["DiffuseTint1"] == pytest.approx(
        (0.04518621, 0.04518621, 0.04518621)
    )

    # All non-colour values land in scalars.
    assert set(scalars) == {
        "TilingScale1",
        "PomSelfShadowStrength",
        "PomDisplacement",
        "GlossMultWear1",
        "GlossMult1",
        "TilingScaleWear1",
        "PomHeightBias",
    }
    assert scalars["GlossMult1"] == pytest.approx(0.80000001)


def test_extract_tint_colors_sugar_over_material() -> None:
    mat = Material(
        public_params={
            "DiffuseTint1": "0.5,0.5,0.5",
            "GlossMult1": "0.8",
        }
    )
    tints = extract_tint_colors(mat)
    assert set(tints) == {"DiffuseTint1"}
    assert tints["DiffuseTint1"] == pytest.approx((0.5, 0.5, 0.5))


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("DiffuseTint", True),
        ("DiffuseTint1", True),
        ("DiffuseTint12", True),
        ("diffusetint1", True),  # case-insensitive
        ("DiffuseTintWear1", False),  # wear → blend layer, not multiply
        ("DirtColor", False),
        ("DustColor", False),
        ("TilingScale1", False),
        ("", False),
    ],
)
def test_is_primary_tint_key(key: str, expected: bool) -> None:
    assert is_primary_tint_key(key) is expected


def test_extract_color_params_loads_real_sc_material() -> None:
    """End-to-end: parse `SC_mat.mtl`, pull tint colours off
    `Anodized_01_A`'s sub-material, verify the expected keys land."""
    fs = RealFileSystem(_FIXTURES)
    root = load_material("SC_mat.mtl", fs)
    assert root is not None
    anodized = next(
        m for m in root.sub_materials if m.name == "Anodized_01_A"
    )
    colors = extract_tint_colors(anodized)
    assert set(colors) == {
        "DirtColor",
        "DiffuseTint1",
        "DiffuseTintWear1",
    }
    primary = {k for k in colors if is_primary_tint_key(k)}
    assert primary == {"DiffuseTint1"}
