from __future__ import annotations

from cryengine_importer.blender.crysis2_tools import (
    CRYSIS1,
    CRYSIS2,
    CRYSIS3,
    PHYSICALIZE_LABELS,
    cryexport_node_name_from_filename,
    detect_crysis1_lod_level,
    extract_cryexport_node_suffix,
    format_export_options,
    get_crytools_profile,
    is_crysis1_piece_child,
    is_cryexport_node_name,
    is_excluded_node_name,
    is_valid_export_filename,
    normalize_physicalize_label,
    parse_export_options,
    parse_material_id_name,
    parse_property_rows,
    shape_key_summary,
    skin_validation_summary,
    suggest_crysis1_lod_name,
    summarize_material_ids,
    validate_pieces_references,
)


def test_material_id_extraction_and_range() -> None:
    info = parse_material_id_name("_7_metal")
    assert info.material_id == 7
    assert info.label == "metal"
    assert info.valid_name
    assert info.in_range

    out_of_range = parse_material_id_name("_32_glass")
    assert out_of_range.material_id == 32
    assert out_of_range.valid_name
    assert not out_of_range.in_range

    missing = parse_material_id_name("metal")
    assert missing.material_id is None
    assert not missing.valid_name


def test_material_id_summary_finds_duplicates_holes_and_invalids() -> None:
    summary = summarize_material_ids(
        ["_0_base", "_2_trim", "_2_alt", "_33_bad", "plain"]
    )
    assert summary.duplicate_ids == (2,)
    assert summary.holes == (1,)
    assert [info.name for info in summary.out_of_range] == ["_33_bad"]
    assert [info.name for info in summary.missing_ids] == ["plain"]


def test_filename_validation_uses_xsi_safe_characters() -> None:
    assert is_valid_export_filename("Crysis2_LOD_01")
    assert not is_valid_export_filename("Crysis 2")
    assert not is_valid_export_filename("bad-name")
    assert not is_valid_export_filename("")


def test_cryexport_node_suffix_and_formatting() -> None:
    assert is_cryexport_node_name("CryExportNode_tank")
    assert is_cryexport_node_name("cryexportnode_tank")
    assert not is_cryexport_node_name("CryExportNode_")
    assert extract_cryexport_node_suffix("CryExportNode_tank") == "tank"
    assert cryexport_node_name_from_filename("objects/tank.cgf") == "CryExportNode_tank"


def test_profile_definitions_and_export_node_styles() -> None:
    assert get_crytools_profile(CRYSIS1).display_label == "Crysis 1 / CE2"
    assert get_crytools_profile(CRYSIS2).max_skin_influences == 5
    assert get_crytools_profile(CRYSIS3).max_skin_influences == 8

    assert cryexport_node_name_from_filename("tank.cgf", profile=CRYSIS1) == "tank_CryExportNode"
    assert cryexport_node_name_from_filename("tank.cgf", profile=CRYSIS2) == "CryExportNode_tank"
    assert cryexport_node_name_from_filename("tank.cgf", profile=CRYSIS3) == "CryExport_tank"
    assert is_cryexport_node_name("tank_CryExportNode", profile=CRYSIS1)
    assert extract_cryexport_node_suffix("tank_CryExportNode", profile=CRYSIS1) == "tank"
    assert is_cryexport_node_name("CryExport_vehicle", profile=CRYSIS3)


def test_excluded_node_prefix_matches_max_tools() -> None:
    assert is_excluded_node_name("_helper")
    assert not is_excluded_node_name("helper")


def test_export_option_string_round_trip() -> None:
    text = (
        "-animationSampleStep 2 -enableKeyOptimization true "
        "rotationPrecision=0.01; positionPrecision=0.02"
    )
    parsed = parse_export_options(text)
    assert parsed == {
        "animationSampleStep": "2",
        "enableKeyOptimization": "true",
        "rotationPrecision": "0.01",
        "positionPrecision": "0.02",
    }
    formatted = format_export_options(parsed)
    assert parse_export_options(formatted) == parsed


def test_property_rows_and_pieces_reference_validation() -> None:
    rows = parse_property_rows("DoNotMerge\npieces=wheel hull; custom = value")
    assert rows == {"DoNotMerge": "true", "pieces": "wheel hull", "custom": "value"}

    validation = validate_pieces_references(rows, ["wheel", "door"])
    assert validation.references == ("wheel", "hull")
    assert validation.missing == ("hull",)


def test_crysis1_lod_and_piece_helpers() -> None:
    assert detect_crysis1_lod_level("tank-LOD2-hull") == 2
    assert detect_crysis1_lod_level("tank_LOD2_hull") is None
    assert suggest_crysis1_lod_name("tank-LOD2-hull") == "tank_LOD2_hull"
    assert is_crysis1_piece_child("wall-piece01")

    validation = validate_pieces_references(
        "pieces=wheel tank-LOD3-hull missing",
        ["wheel"],
        profile=CRYSIS1,
    )
    assert validation.references == ("wheel", "tank-LOD3-hull", "missing")
    assert validation.missing == ("missing",)


def test_physicalize_labels_are_canonical() -> None:
    assert PHYSICALIZE_LABELS == ("Default", "ProxyNoDraw", "NoCollide", "Obstruct")
    assert normalize_physicalize_label("proxynodraw") == "ProxyNoDraw"
    assert normalize_physicalize_label("unknown") == "Default"


def test_skin_and_shape_key_summaries_are_human_readable() -> None:
    skin = skin_validation_summary(
        mesh_count=2,
        meshes_without_armature=1,
        missing_armature_objects=0,
        unweighted_vertices=5,
        non_normalized_vertices=2,
        skeleton_roots=["Bip01"],
    )
    assert "Meshes without armature: 1" in skin
    assert "Skeleton roots: Bip01" in skin

    shape = shape_key_summary("head", ["Basis", "blink"], ["blink"])
    assert shape == ["head: 2 shape key(s)", "Muted/zero keys: blink"]